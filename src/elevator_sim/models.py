"""Core domain models for the elevator simulation.

Three entities:

* :class:`Request`   - the raw input row (time, id, source, dest).
* :class:`Passenger` - a request plus its lifecycle timestamps, from which the
  wait / travel / total times are derived.
* :class:`Elevator`  - a single car. Owns its movement (one floor per tick) and
  its route, computed with a LOOK ("elevator algorithm") scan.

Design notes (see DECISIONS.md for the full reasoning):

* Time is discrete. One tick == one floor of vertical travel.
* A stop costs one extra "dwell" tick during which passengers board/alight.
* Destination Dispatch: a passenger's origin AND destination are known at
  request time, and the assignment to a car is fixed once made.
"""

from dataclasses import dataclass, field
from enum import IntEnum


class Direction(IntEnum):
    """Travel direction. Values double as the per-tick floor delta."""

    UP = 1
    DOWN = -1
    IDLE = 0


@dataclass(frozen=True)
class Request:
    """A single immutable input request: a passenger wants to travel.

    ``source`` and ``dest`` are floor numbers; ``time`` is the integer tick at
    which the request enters the system.
    """

    time: int
    id: str
    source: int
    dest: int

    def __post_init__(self) -> None:
        if self.source == self.dest:
            raise ValueError(f"request {self.id}: source and dest must differ (both {self.source})")
        if self.time < 0:
            raise ValueError(f"request {self.id}: time must be non-negative")

    @property
    def direction(self) -> Direction:
        """The direction this passenger ultimately wants to travel."""
        return Direction.UP if self.dest > self.source else Direction.DOWN


@dataclass
class Passenger:
    """A request being tracked through its lifecycle.

    Timestamps are stamped by the simulation:

    * ``request.time`` - when the passenger appeared (wait clock starts).
    * ``pickup_time``  - the tick they boarded a car.
    * ``dropoff_time`` - the tick they reached their destination.
    """

    request: Request
    pickup_time: int | None = None
    dropoff_time: int | None = None
    assigned_elevator: int | None = None

    @property
    def id(self) -> str:
        return self.request.id

    @property
    def source(self) -> int:
        return self.request.source

    @property
    def dest(self) -> int:
        return self.request.dest

    @property
    def request_time(self) -> int:
        return self.request.time

    @property
    def wait_time(self) -> int | None:
        """Ticks between requesting and being picked up."""
        if self.pickup_time is None:
            return None
        return self.pickup_time - self.request_time

    @property
    def travel_time(self) -> int | None:
        """Ticks spent on board, from pickup to drop-off."""
        if self.pickup_time is None or self.dropoff_time is None:
            return None
        return self.dropoff_time - self.pickup_time

    @property
    def total_time(self) -> int | None:
        """wait_time + travel_time; the metric the brief asks us to minimise."""
        if self.wait_time is None or self.travel_time is None:
            return None
        return self.wait_time + self.travel_time

    @property
    def delivered(self) -> bool:
        return self.dropoff_time is not None

    @property
    def picked_up(self) -> bool:
        return self.pickup_time is not None


@dataclass
class Elevator:
    """A single elevator car.

    The car services two kinds of stop:

    * **drop-offs** - floors that boarded passengers want to reach.
    * **pickups**   - source floors of passengers assigned but not yet aboard.

    Routing uses the LOOK algorithm: keep going in the current direction,
    serving every stop along the way, then reverse when there is nothing
    further ahead. This avoids direction thrashing and is easy to reason about.
    """

    id: int
    capacity: int
    current_floor: int = 0
    direction: Direction = Direction.IDLE

    # Express elevators serve only a subset of floors (e.g. lobby + high floors,
    # skipping the rest). ``None`` means a standard car that serves every floor.
    serviceable_floors: frozenset[int] | None = None

    # Passengers physically aboard the car.
    onboard: list[Passenger] = field(default_factory=list)
    # Passengers assigned to this car but still waiting at their source floor.
    waiting: list[Passenger] = field(default_factory=list)

    # --- introspection -------------------------------------------------

    @property
    def load(self) -> int:
        return len(self.onboard)

    @property
    def is_full(self) -> bool:
        return self.load >= self.capacity

    @property
    def is_express(self) -> bool:
        return self.serviceable_floors is not None

    def can_serve(self, floor: int) -> bool:
        """Whether this car is allowed to stop at ``floor``."""
        return self.serviceable_floors is None or floor in self.serviceable_floors

    def can_serve_request(self, request: Request) -> bool:
        """Whether this car can both pick up and drop off ``request``."""
        return self.can_serve(request.source) and self.can_serve(request.dest)

    def has_work(self) -> bool:
        return bool(self.onboard or self.waiting)

    def dropoff_floors(self) -> set[int]:
        return {p.dest for p in self.onboard}

    def pickup_floors(self) -> set[int]:
        return {p.source for p in self.waiting}

    def target_floors(self) -> set[int]:
        """All floors this car must eventually visit."""
        return self.dropoff_floors() | self.pickup_floors()

    # --- routing (LOOK) ------------------------------------------------

    def should_service_here(self) -> bool:
        """True if the car should open its doors at the current floor this tick.

        We service the current floor when there is someone to drop off here, or
        someone to pick up here *and* we have room. The capacity check is what
        prevents a full car from getting stuck dwelling forever at a pickup
        floor it cannot satisfy - instead it moves on, frees space at a
        drop-off, and the LOOK scan brings it back later.
        """
        if self.current_floor in self.dropoff_floors():
            return True
        return bool(not self.is_full and self.current_floor in self.pickup_floors())

    def next_move_target(self) -> int | None:
        """The next floor to move toward (never the current floor).

        Implements the LOOK scan: prefer stops ahead in the current direction;
        when none remain ahead, reverse toward the nearest stop behind.
        """
        stops = {f for f in self.target_floors() if f != self.current_floor}
        if not stops:
            return None

        above = sorted(f for f in stops if f > self.current_floor)
        below = sorted((f for f in stops if f < self.current_floor), reverse=True)

        if self.direction == Direction.UP:
            return above[0] if above else below[0]
        if self.direction == Direction.DOWN:
            return below[0] if below else above[0]
        # IDLE: head toward whichever stop is closest.
        return min(stops, key=lambda f: (abs(f - self.current_floor), f))

    def step(self) -> str:
        """Advance the car by one tick when it is *not* servicing a floor.

        Returns the action taken: ``"move"`` or ``"idle"``. (Door servicing is
        driven by the simulation, which calls :meth:`should_service_here` first.)
        """
        target = self.next_move_target()
        if target is None:
            self.direction = Direction.IDLE
            return "idle"

        if target > self.current_floor:
            self.current_floor += 1
            self.direction = Direction.UP
        else:
            self.current_floor -= 1
            self.direction = Direction.DOWN
        return "move"
