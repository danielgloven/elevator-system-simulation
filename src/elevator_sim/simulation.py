"""The discrete-time simulation engine.

Each tick, in order:

1. **Release** every request whose ``time`` equals the current tick (and never
   look any further ahead than that), wrapping each in a :class:`Passenger`.
2. **Assign** each freshly released passenger to a car via the scheduler.
3. For every car, **service** the current floor (board/alight, costing a dwell
   tick) if it should, otherwise **move** one floor along its LOOK route.
4. **Log** every car's floor for this tick.

The loop runs until every passenger has been delivered, which - because the
LOOK route always retains unserved stops - guarantees the brief's first
objective: no passenger waits forever.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from .models import Elevator, Passenger, Request
from .scheduler import Scheduler


@dataclass
class SimulationResult:
    """Everything an analysis or report needs after a run."""

    passengers: list[Passenger]
    #: positions[t][i] == floor of elevator i at tick t.
    positions: list[list[int]]
    num_elevators: int
    num_floors: int
    capacity: int
    ticks: int  # number of logged time steps (0 .. ticks-1)


class Simulation:
    """A configurable Destination Dispatch elevator simulation."""

    def __init__(
        self,
        requests: Sequence[Request],
        num_elevators: int = 3,
        num_floors: int = 10,
        capacity: int = 8,
        scheduler: Scheduler | None = None,
        start_floor: int = 1,
        max_ticks: int | None = None,
    ) -> None:
        if num_elevators < 1:
            raise ValueError("num_elevators must be >= 1")
        if num_floors < 2:
            raise ValueError("num_floors must be >= 2")
        if capacity < 1:
            raise ValueError("capacity must be >= 1")
        if not (1 <= start_floor <= num_floors):
            raise ValueError(f"start_floor must be in [1, {num_floors}]")

        # Floors are 1-indexed (ground == 1), matching the building convention
        # and the sample data (floors up to 51).
        for r in requests:
            for label, floor in (("source", r.source), ("dest", r.dest)):
                if not (1 <= floor <= num_floors):
                    raise ValueError(
                        f"request {r.id}: {label} floor {floor} outside [1, {num_floors}]"
                    )

        if scheduler is None:
            from .scheduler import NearestCarScheduler

            scheduler = NearestCarScheduler()

        self.num_elevators = num_elevators
        self.num_floors = num_floors
        self.capacity = capacity
        self.scheduler = scheduler

        self.elevators: list[Elevator] = [
            Elevator(id=i, capacity=capacity, current_floor=start_floor)
            for i in range(num_elevators)
        ]

        # Group requests by release tick so we never inspect future requests.
        self._by_time: dict[int, list[Request]] = defaultdict(list)
        for r in requests:
            self._by_time[r.time].append(r)
        self._last_request_tick = max((r.time for r in requests), default=0)
        self._total = len(requests)

        # Generous upper bound on run length; trips only on a routing bug.
        self.max_ticks = max_ticks or (
            self._last_request_tick + 4 * num_floors * (self._total + 1) + 1000
        )

        self.passengers: list[Passenger] = []
        self.positions: list[list[int]] = []

    # ------------------------------------------------------------------

    def run(self) -> SimulationResult:
        """Run the simulation to completion and return the result."""
        delivered = 0
        t = 0
        while delivered < self._total or t <= self._last_request_tick:
            if t > self.max_ticks:
                raise RuntimeError(
                    f"simulation exceeded {self.max_ticks} ticks - likely a routing bug"
                )

            self._release(t)
            for elevator in self.elevators:
                delivered += self._advance(elevator, t)

            self.positions.append([e.current_floor for e in self.elevators])
            t += 1

        return SimulationResult(
            passengers=self.passengers,
            positions=self.positions,
            num_elevators=self.num_elevators,
            num_floors=self.num_floors,
            capacity=self.capacity,
            ticks=len(self.positions),
        )

    # ------------------------------------------------------------------

    def _release(self, t: int) -> None:
        """Admit requests timestamped for tick ``t`` and assign each a car."""
        for request in self._by_time.get(t, ()):
            passenger = Passenger(request=request)
            car_id = self.scheduler.assign(passenger, self.elevators, t)
            passenger.assigned_elevator = car_id
            self.elevators[car_id].waiting.append(passenger)
            self.passengers.append(passenger)

    def _advance(self, elevator: Elevator, t: int) -> int:
        """Advance one car by one tick. Returns how many passengers it delivered.

        If the car should open its doors here it spends the tick servicing
        (and does not move); otherwise it moves one floor along its route.
        """
        if elevator.should_service_here():
            return self._service(elevator, t)
        elevator.step()
        return 0

    def _service(self, elevator: Elevator, t: int) -> int:
        """Drop off arrivals, then board waiting passengers (capacity allowing)."""
        floor = elevator.current_floor

        # Alight everyone whose destination is this floor.
        staying = []
        delivered = 0
        for p in elevator.onboard:
            if p.dest == floor:
                p.dropoff_time = t
                delivered += 1
            else:
                staying.append(p)
        elevator.onboard = staying

        # Board waiting passengers at this floor, in arrival order, until full.
        still_waiting = []
        for p in elevator.waiting:
            if p.source == floor and not elevator.is_full:
                p.pickup_time = t
                elevator.onboard.append(p)
            else:
                still_waiting.append(p)
        elevator.waiting = still_waiting

        return delivered
