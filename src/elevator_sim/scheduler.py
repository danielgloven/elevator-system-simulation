"""Schedulers: how an incoming request is assigned to an elevator.

The :class:`Scheduler` base class defines a single decision point - given a new
passenger and the current fleet, return the id of the car to assign them to.
This keeps the *assignment policy* cleanly separable from the *mechanics* of
movement (in :mod:`models`) and the tick loop (in :mod:`simulation`), so new
strategies (zone-based, express, etc.) can be added without touching either.

Strategies register themselves in :data:`SCHEDULERS` so the CLI can select one
by name.

First-pass strategies:

* :class:`NearestCarScheduler` (default) - assign to the car that can reach the
  pickup floor soonest, with a light load-balancing tie-breaker.
* :class:`RoundRobinScheduler` - cycle through cars in order. Trivial, but it
  proves the interface is genuinely pluggable and gives us a baseline to
  compare against in the write-up.
"""

from __future__ import annotations

from typing import Dict, List, Type

from .models import Direction, Elevator, Passenger


class Scheduler:
    """Base class. Subclasses implement :meth:`assign`."""

    name: str = "base"

    def assign(self, passenger: Passenger, elevators: List[Elevator], now: int) -> int:
        """Return the id of the elevator to assign ``passenger`` to.

        Called exactly once per passenger, at the tick the request appears
        (Destination Dispatch: the choice is immediate and final).
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
    LOAD_PENALTY = 0.5

    def assign(self, passenger: Passenger, elevators: List[Elevator], now: int) -> int:
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


class RoundRobinScheduler(Scheduler):
    """Assign cars in strict rotation, ignoring position. A naive baseline."""

    name = "round_robin"

    def __init__(self) -> None:
        self._next = 0

    def assign(self, passenger: Passenger, elevators: List[Elevator], now: int) -> int:
        chosen = elevators[self._next % len(elevators)]
        self._next += 1
        return chosen.id


#: Registry of available strategies, keyed by name for CLI selection.
SCHEDULERS: Dict[str, Type[Scheduler]] = {
    NearestCarScheduler.name: NearestCarScheduler,
    RoundRobinScheduler.name: RoundRobinScheduler,
}


def get_scheduler(name: str) -> Scheduler:
    """Instantiate a scheduler by name, or raise a helpful error."""
    try:
        return SCHEDULERS[name]()
    except KeyError:
        available = ", ".join(sorted(SCHEDULERS))
        raise ValueError(f"unknown scheduler {name!r}; available: {available}") from None
