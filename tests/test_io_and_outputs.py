"""Tests for input loading, statistics/output writers, schedulers, and the CLI."""

import csv

import pytest

from elevator_sim.cli import main
from elevator_sim.io_utils import load_requests
from elevator_sim.models import Direction, Elevator, Passenger, Request
from elevator_sim.scheduler import (
    NearestCarScheduler,
    RoundRobinScheduler,
    Scheduler,
    get_scheduler,
)
from elevator_sim.simulation import Simulation
from elevator_sim.stats import (
    compute_statistics,
    write_passenger_log,
    write_positions_log,
    write_summary,
)


def _write_csv(path, rows):
    with open(path, "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["time", "id", "source", "dest"])
        writer.writerows(rows)


# --- io_utils ------------------------------------------------------------


def test_load_requests_parses_and_sorts(tmp_path):
    path = tmp_path / "r.csv"
    _write_csv(path, [[5, "b", 2, 9], [0, "a", 1, 10]])
    requests = load_requests(str(path))
    assert [r.id for r in requests] == ["a", "b"]  # sorted by time
    assert requests[0].source == 1 and requests[0].dest == 10


def test_load_requests_rejects_missing_columns(tmp_path):
    path = tmp_path / "bad.csv"
    with open(path, "w", newline="") as fh:
        fh.write("time,id\n0,a\n")
    with pytest.raises(ValueError, match="missing columns"):
        load_requests(str(path))


# --- statistics & writers ------------------------------------------------


def _small_result():
    requests = [
        Request(time=0, id="p1", source=1, dest=5),
        Request(time=1, id="p2", source=4, dest=2),
    ]
    return Simulation(requests, num_elevators=2, num_floors=5, capacity=2).run()


def test_compute_statistics_basic():
    stats = compute_statistics(_small_result())
    assert stats.delivered == 2
    assert stats.wait is not None
    assert stats.total.minimum <= stats.total.average <= stats.total.maximum
    assert "wait_time" in stats.render()


def test_compute_statistics_with_no_delivered_passengers():
    # An empty run: no passengers, so metrics are absent but render still works.
    result = Simulation([], num_elevators=1, num_floors=3).run()
    stats = compute_statistics(result)
    assert stats.delivered == 0
    assert stats.wait is None
    assert "PASSENGER SUMMARY" in stats.render()


def test_writers_emit_files(tmp_path):
    result = _small_result()
    stats = compute_statistics(result)
    pos, pas, summ = (
        tmp_path / "positions.csv",
        tmp_path / "passengers.csv",
        tmp_path / "summary.txt",
    )
    write_positions_log(result, str(pos))
    write_passenger_log(result, str(pas))
    write_summary(stats, str(summ))

    # positions: header + one row per tick.
    pos_rows = list(csv.reader(pos.open()))
    assert pos_rows[0] == ["time", "elevator_0", "elevator_1"]
    assert len(pos_rows) == result.ticks + 1

    pas_rows = list(csv.DictReader(pas.open()))
    assert {r["id"] for r in pas_rows} == {"p1", "p2"}
    assert summ.read_text().strip().endswith("=" * 56)


# --- schedulers ----------------------------------------------------------


def test_get_scheduler_unknown_name_raises():
    with pytest.raises(ValueError, match="unknown scheduler"):
        get_scheduler("does_not_exist")


def test_get_scheduler_returns_instances():
    assert isinstance(get_scheduler("nearest_car"), NearestCarScheduler)
    assert isinstance(get_scheduler("round_robin"), RoundRobinScheduler)


def test_base_scheduler_is_abstract():
    with pytest.raises(NotImplementedError):
        Scheduler().assign(Passenger(request=Request(time=0, id="x", source=1, dest=2)), [], 0)


def test_nearest_car_handles_downward_car_with_source_above():
    # Exercise the DOWN-direction "source above" branch of the cost estimate.
    sched = NearestCarScheduler()
    car = Elevator(id=0, capacity=4, current_floor=5, direction=Direction.DOWN)
    car.onboard = [Passenger(request=Request(time=0, id="a", source=5, dest=1))]
    p = Passenger(request=Request(time=0, id="b", source=9, dest=1))
    assert sched.assign(p, [car], 0) == 0


# --- CLI -----------------------------------------------------------------


def test_cli_end_to_end_writes_outputs(tmp_path):
    out = tmp_path / "out"
    code = main(
        [
            "--requests",
            "data/requests.csv",
            "--elevators",
            "2",
            "--floors",
            "51",
            "--output-dir",
            str(out),
        ]
    )
    assert code == 0
    assert (out / "positions.csv").exists()
    assert (out / "passengers.csv").exists()
    assert (out / "summary.txt").exists()


def test_cli_reports_empty_input(tmp_path):
    empty = tmp_path / "empty.csv"
    with open(empty, "w", newline="") as fh:
        fh.write("time,id,source,dest\n")
    assert main(["--requests", str(empty)]) == 1
