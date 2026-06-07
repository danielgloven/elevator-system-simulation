"""Tests covering the brief's objectives and key invariants."""

import pytest

from elevator_sim.models import Direction, Elevator, Passenger, Request
from elevator_sim.scheduler import NearestCarScheduler, RoundRobinScheduler
from elevator_sim.simulation import Simulation
from elevator_sim.stats import compute_statistics


def run(requests, **kwargs):
    kwargs.setdefault("num_elevators", 2)
    kwargs.setdefault("num_floors", 10)
    kwargs.setdefault("capacity", 4)
    return Simulation(requests, **kwargs).run()


# --- models --------------------------------------------------------------


def test_request_rejects_equal_source_dest():
    with pytest.raises(ValueError):
        Request(time=0, id="x", source=3, dest=3)


def test_passenger_time_math():
    p = Passenger(request=Request(time=5, id="p", source=1, dest=10))
    p.pickup_time = 8
    p.dropoff_time = 20
    assert p.wait_time == 3
    assert p.travel_time == 12
    assert p.total_time == 15


def test_look_prefers_current_direction_then_reverses():
    e = Elevator(id=0, capacity=4, current_floor=5, direction=Direction.UP)
    e.waiting = [
        Passenger(request=Request(time=0, id="a", source=8, dest=1)),  # pickup @8
        Passenger(request=Request(time=0, id="b", source=2, dest=9)),  # pickup @2
    ]
    # Heading up from 5: serve the stop above (8) before the one below (2).
    assert e.next_move_target() == 8


# --- core objectives -----------------------------------------------------


def test_every_passenger_is_eventually_delivered():
    requests = [
        Request(time=0, id="p1", source=1, dest=10),
        Request(time=0, id="p2", source=1, dest=8),
        Request(time=3, id="p3", source=9, dest=2),
        Request(time=7, id="p4", source=5, dest=1),
    ]
    result = run(requests)
    assert all(p.delivered for p in result.passengers)
    # Drop-off can never precede pickup, which can never precede the request.
    for p in result.passengers:
        assert p.request_time <= p.pickup_time <= p.dropoff_time


def test_capacity_is_never_exceeded():
    # 10 passengers all from floor 1 going up, capacity 2 -> must batch them.
    requests = [Request(time=0, id=f"p{i}", source=1, dest=10) for i in range(10)]
    sim = Simulation(requests, num_elevators=1, num_floors=10, capacity=2)

    max_seen = 0
    # Re-run tick by tick to watch occupancy. (Mirrors Simulation.run.)
    delivered = 0
    t = 0
    while delivered < len(requests) or t <= sim._last_request_tick:
        sim._release(t)
        for e in sim.elevators:
            delivered += sim._advance(e, t)
            max_seen = max(max_seen, e.load)
        sim.positions.append([e.current_floor for e in sim.elevators])
        t += 1

    assert max_seen <= 2
    assert all(p.delivered for p in sim.passengers)


def test_no_peek_ahead_a_late_request_is_not_served_early():
    # A passenger requesting at t=50 cannot be picked up before t=50.
    requests = [Request(time=50, id="late", source=3, dest=7)]
    result = run(requests)
    late = result.passengers[0]
    assert late.pickup_time >= 50


def test_simulation_is_deterministic():
    requests = [
        Request(time=0, id="p1", source=1, dest=9),
        Request(time=1, id="p2", source=4, dest=2),
        Request(time=2, id="p3", source=7, dest=1),
    ]
    a = run(requests).positions
    b = run(requests).positions
    assert a == b


# --- statistics ----------------------------------------------------------


def test_hand_computed_single_passenger_stats():
    # One car at floor 1; passenger requests at t=0 from 1 -> 5.
    # t0: car at 1, services (boards, dwell). pickup=0.
    # t1..t4: moves 1->2->3->4->5.
    # t5: services floor 5 (drop off). dropoff=5.
    # wait=0, travel=5, total=5.
    requests = [Request(time=0, id="solo", source=1, dest=5)]
    result = Simulation(requests, num_elevators=1, num_floors=5, capacity=1).run()
    p = result.passengers[0]
    assert p.wait_time == 0
    assert p.travel_time == 5
    assert p.total_time == 5

    stats = compute_statistics(result)
    assert stats.total.minimum == stats.total.maximum == 5
    assert stats.delivered == 1


# --- schedulers ----------------------------------------------------------


@pytest.mark.parametrize("scheduler", [NearestCarScheduler(), RoundRobinScheduler()])
def test_all_schedulers_serve_everyone(scheduler):
    requests = [
        Request(time=0, id="p1", source=1, dest=10),
        Request(time=2, id="p2", source=9, dest=1),
        Request(time=4, id="p3", source=5, dest=8),
    ]
    result = run(requests, scheduler=scheduler, num_elevators=3)
    assert all(p.delivered for p in result.passengers)
