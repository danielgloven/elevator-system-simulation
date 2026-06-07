"""Tests for the bonus features: zone-based scheduling and express elevators."""

import pytest

from elevator_sim.compare import compare_strategies, render_comparison
from elevator_sim.models import Elevator, Request
from elevator_sim.scheduler import ZoneBasedScheduler, get_scheduler
from elevator_sim.simulation import Simulation


def _rush(n=20):
    # Mostly lobby -> high, with a few inter-floor trips.
    reqs = []
    for i in range(n):
        if i % 4 == 0:
            src, dest = 10 + i % 30, 2
        else:
            src, dest = 1, 12 + (i * 3) % 38
        reqs.append(Request(time=i // 2, id=f"p{i}", source=src, dest=dest))
    return reqs


# --- zone-based ----------------------------------------------------------


def test_zone_setup_partitions_floors():
    z = ZoneBasedScheduler()
    z.setup(num_floors=50, num_elevators=5)
    # 50 floors / 5 cars -> 10 floors each, contiguous and covering the range.
    assert z._zones[0] == (1, 10)
    assert z._zones[4] == (41, 50)


def test_zone_based_delivers_everyone():
    result = Simulation(
        _rush(), scheduler=ZoneBasedScheduler(), num_elevators=3, num_floors=51, capacity=6
    ).run()
    assert all(p.delivered for p in result.passengers)


def test_zone_based_assigns_source_to_owning_zone():
    z = ZoneBasedScheduler()
    z.setup(num_floors=30, num_elevators=3)  # zones: 1-10, 11-20, 21-30
    cars = [Elevator(id=i, capacity=4, current_floor=1) for i in range(3)]
    from elevator_sim.models import Passenger

    p = Passenger(request=Request(time=0, id="x", source=25, dest=2))
    assert z.assign(p, cars, 0) == 2  # floor 25 is in car 2's zone


# --- express elevators ---------------------------------------------------


def test_elevator_can_serve():
    express = Elevator(id=0, capacity=4, serviceable_floors=frozenset({1, 30, 31, 32}))
    assert express.is_express
    assert express.can_serve(30)
    assert not express.can_serve(5)
    assert express.can_serve_request(Request(time=0, id="a", source=1, dest=30))
    assert not express.can_serve_request(Request(time=0, id="b", source=5, dest=30))


def test_express_config_requires_min_floor():
    with pytest.raises(ValueError, match="express_min_floor is required"):
        Simulation(_rush(), num_elevators=3, num_floors=51, num_express=1)


def test_express_needs_a_standard_car():
    with pytest.raises(ValueError, match="must be < num_elevators"):
        Simulation(_rush(), num_elevators=2, num_floors=51, num_express=2, express_min_floor=26)


def test_express_min_floor_in_range():
    with pytest.raises(ValueError, match="express_min_floor must be in"):
        Simulation(_rush(), num_elevators=3, num_floors=51, num_express=1, express_min_floor=99)


def test_express_serves_everyone_and_respects_constraints():
    sim = Simulation(
        _rush(24), num_elevators=3, num_floors=51, capacity=6, num_express=1, express_min_floor=26
    )
    result = sim.run()
    assert all(p.delivered for p in result.passengers)
    # No passenger may be assigned to a car that cannot serve their trip.
    by_id = {e.id: e for e in sim.elevators}
    for p in result.passengers:
        car = by_id[p.assigned_elevator]
        assert car.can_serve(p.source) and car.can_serve(p.dest)


def test_express_car_is_actually_express():
    sim = Simulation(_rush(), num_elevators=3, num_floors=51, num_express=1, express_min_floor=26)
    # Last car is express; the others are standard.
    assert sim.elevators[2].is_express
    assert not sim.elevators[0].is_express


# --- comparison harness --------------------------------------------------


def test_compare_strategies_runs_all():
    rows = compare_strategies(
        _rush(),
        sorted({"nearest_car", "zone_based", "round_robin"}),
        num_elevators=3,
        num_floors=51,
        capacity=6,
    )
    assert {r.strategy for r in rows} == {"nearest_car", "zone_based", "round_robin"}
    assert all(r.delivered == len(_rush()) for r in rows)
    text = render_comparison(rows)
    assert "STRATEGY COMPARISON" in text and "nearest_car" in text


def test_get_scheduler_includes_zone_based():
    assert isinstance(get_scheduler("zone_based"), ZoneBasedScheduler)


# --- CLI integration -----------------------------------------------------


def test_cli_compare_mode_writes_table(tmp_path):
    from elevator_sim.cli import main

    out = tmp_path / "out"
    code = main(["--requests", "data/rush_hour.csv", "--compare", "--output-dir", str(out)])
    assert code == 0
    assert (out / "comparison.txt").exists()


def test_cli_express_run(tmp_path):
    from elevator_sim.cli import main

    out = tmp_path / "out"
    code = main(
        [
            "--requests",
            "data/rush_hour.csv",
            "--num-express",
            "1",
            "--express-min-floor",
            "26",
            "--output-dir",
            str(out),
        ]
    )
    assert code == 0
    assert (out / "summary.txt").exists()
