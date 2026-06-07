"""Schedulers: how an incoming request is assigned to an elevator.

The :class:`Scheduler` base class defines a single decision point - given a new
passenger and the current fleet, return the id of the car to assign them to.
This keeps the *assignment policy* cleanly separable from the *mechanics* of
movement (in :mod:`models`) and the tick loop (in :mod:`simulation`), so new
strategies (zone-based, express, etc.) can be added without touching either.

Strategies register themselves in :data:`SCHEDULERS` so the CLI can select one
by name.

Strategies:

* :class:`NearestCarScheduler` (default) - assign to the car that can reach the
  pickup floor soonest, with a light load-balancing tie-breaker.
* :class:`ZoneBasedScheduler` - partition the building into zones, one per car,
  and assign by which zone owns the request's source floor.
* :class:`RoundRobinScheduler` - cycle through cars in order. Trivial, but it
  proves the interface is genuinely pluggable and gives us a baseline to
  compare against in the write-up.

Note on express elevators: the *engine* (see :mod:`simulation`) only ever passes
a scheduler the cars that can actually serve a given request, so schedulers never
need to know about express constraints - they just optimise among feasible cars.
"""

from .models import Direction, Elevator, Passenger


class Scheduler:
    """Base class. Subclasses implement :meth:`assign`."""

    name: str = "base"

    def setup(self, num_floors: int, num_elevators: int) -> None:
        """Optional one-time hook so a strategy can learn the building shape.

        Called once by the simulation at construction. Default is a no-op;
        strategies that need the floor/elevator counts (e.g. zoning) override it.
        """

    def assign(self, passenger: Passenger, elevators: list[Elevator], now: int) -> int:
        """Return the id of the elevator to assign ``passenger`` to.

        ``elevators`` is the set of cars *eligible* to serve this passenger
        (the engine has already filtered out any express car that cannot reach
        the source or destination). Called exactly once per passenger, at the
        tick the request appears (Destination Dispatch: immediate and final).
        """
        raise NotImplementedError


class NearestCarScheduler(Scheduler):
    """Assign each request to the car with the lowest estimated pickup cost.

    The cost is an estimate of how many ticks until the car could reach the
    passenger's source floor, given where it is and which way it is heading:

    * idle car            -> straight-line distance to the source;
    * source ahead on the
      car's current path   -> distance directly to the source;
    * source behind the
      car's direction      -> it must first run out its current direction to its
                              furthest committed stop, then come back.

    A small penalty proportional to the car's current commitments (onboard +
    waiting) is added so work spreads across the fleet instead of piling onto
    one already-busy car. The estimate is deliberately cheap rather than a full
    route re-simulation - see DECISIONS.md for that trade-off.
    """

    name = "nearest_car"

    #: Weight of the load-balancing term, in "ticks per committed passenger".
    #: Tuned to 2.0: under burst lobby traffic the "nearest" car is the same for
    #: everyone, so a too-small penalty piles the whole rush onto one car. At 2.0
    #: the rush scenario's avg total time drops ~26% vs 0.5 with no regression on
    #: lighter scenarios. See DECISIONS.md.
    LOAD_PENALTY = 2.0

    def assign(self, passenger: Passenger, elevators: list[Elevator], now: int) -> int:
        best_id = elevators[0].id
        best_cost = float("inf")
        for elevator in elevators:
            cost = self._estimate_cost(elevator, passenger)
            if cost < best_cost:
                best_cost = cost
                best_id = elevator.id
        return best_id

    def _estimate_cost(self, elevator: Elevator, passenger: Passenger) -> float:
        pos = elevator.current_floor
        src = passenger.source
        load_term = self.LOAD_PENALTY * (elevator.load + len(elevator.waiting))

        if elevator.direction == Direction.IDLE or not elevator.has_work():
            return abs(pos - src) + load_term

        if elevator.direction == Direction.UP:
            if src >= pos:
                return (src - pos) + load_term
            # Source is below an upward-moving car: finish upward, then descend.
            apex = max(elevator.target_floors() | {pos})
            return (apex - pos) + (apex - src) + load_term

        # direction == DOWN
        if src <= pos:
            return (pos - src) + load_term
        # Source is above a downward-moving car: finish downward, then ascend.
        nadir = min(elevator.target_floors() | {pos})
        return (pos - nadir) + (src - nadir) + load_term


class ZoneBasedScheduler(Scheduler):
    """Partition the building into contiguous zones, one per elevator.

    Each car ``i`` "owns" a band of floors; a request is assigned to the car
    whose zone contains its source. The idea is locality: a car mostly stays
    near its zone, so it's usually close to its next pickup. The classic
    trade-off is uneven load - if all the traffic is in one zone, that car
    saturates while others sit idle (good fairness within a zone, poor global
    efficiency under skewed demand). See DECISIONS.md.

    If the zone-owning car can't serve a request (e.g. it's an express car the
    engine filtered out), we fall back to the eligible car whose zone is
    nearest to the source, breaking ties by current commitment.
    """

    name = "zone_based"

    def __init__(self) -> None:
        # Maps elevator id -> (low_floor, high_floor) inclusive.
        self._zones: dict[int, tuple[int, int]] = {}

    def setup(self, num_floors: int, num_elevators: int) -> None:
        # Split floors 1..num_floors into num_elevators near-equal bands.
        size = -(-num_floors // num_elevators)  # ceil division
        for i in range(num_elevators):
            low = 1 + i * size
            high = min(num_floors, (i + 1) * size)
            if low > num_floors:  # more cars than floors: park extras on top
                low = high = num_floors
            self._zones[i] = (low, high)

    def _distance_to_zone(self, elevator_id: int, floor: int) -> int:
        low, high = self._zones.get(elevator_id, (floor, floor))
        if low <= floor <= high:
            return 0
        return min(abs(floor - low), abs(floor - high))

    def assign(self, passenger: Passenger, elevators: list[Elevator], now: int) -> int:
        src = passenger.source
        return min(
            elevators,
            key=lambda e: (
                self._distance_to_zone(e.id, src),
                e.load + len(e.waiting),
                e.id,
            ),
        ).id


class RoundRobinScheduler(Scheduler):
    """Assign cars in strict rotation, ignoring position. A naive baseline."""

    name = "round_robin"

    def __init__(self) -> None:
        self._next = 0

    def assign(self, passenger: Passenger, elevators: list[Elevator], now: int) -> int:
        chosen = elevators[self._next % len(elevators)]
        self._next += 1
        return chosen.id


#: Registry of available strategies, keyed by name for CLI selection.
SCHEDULERS: dict[str, type[Scheduler]] = {
    NearestCarScheduler.name: NearestCarScheduler,
    ZoneBasedScheduler.name: ZoneBasedScheduler,
    RoundRobinScheduler.name: RoundRobinScheduler,
}


def get_scheduler(name: str) -> Scheduler:
    """Instantiate a scheduler by name, or raise a helpful error."""
    try:
        return SCHEDULERS[name]()
    except KeyError:
        available = ", ".join(sorted(SCHEDULERS))
        raise ValueError(f"unknown scheduler {name!r}; available: {available}") from None
