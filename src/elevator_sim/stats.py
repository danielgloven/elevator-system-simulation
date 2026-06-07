"""Summary statistics and output writers for a finished simulation."""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass

from .simulation import SimulationResult


@dataclass
class MetricSummary:
    """min / max / average for a single metric across all passengers."""

    label: str
    minimum: int
    maximum: int
    average: float
    count: int

    def as_line(self) -> str:
        return (
            f"{self.label:<12} min={self.minimum:>4}  "
            f"max={self.maximum:>4}  avg={self.average:>7.2f}  (n={self.count})"
        )


def _summarise(label: str, values: list[int]) -> MetricSummary | None:
    if not values:
        return None
    return MetricSummary(
        label=label,
        minimum=min(values),
        maximum=max(values),
        average=sum(values) / len(values),
        count=len(values),
    )


@dataclass
class Statistics:
    """Aggregate statistics plus a few notable observations."""

    wait: MetricSummary | None
    travel: MetricSummary | None
    total: MetricSummary | None
    delivered: int
    requested: int
    ticks: int
    longest_wait_passenger: str | None
    longest_total_passenger: str | None

    def render(self) -> str:
        lines = ["=" * 56, "PASSENGER SUMMARY STATISTICS", "=" * 56]
        for metric in (self.wait, self.travel, self.total):
            if metric is not None:
                lines.append(metric.as_line())
        lines.append("-" * 56)
        lines.append(f"Passengers delivered : {self.delivered} / {self.requested}")
        lines.append(f"Simulation length    : {self.ticks} ticks")
        if self.longest_wait_passenger:
            lines.append(f"Longest wait         : {self.longest_wait_passenger}")
        if self.longest_total_passenger:
            lines.append(f"Longest total time   : {self.longest_total_passenger}")
        lines.append("=" * 56)
        return "\n".join(lines)


def compute_statistics(result: SimulationResult) -> Statistics:
    """Derive wait/travel/total summaries and observations from a result."""
    delivered = [p for p in result.passengers if p.delivered]

    waits = [p.wait_time for p in delivered if p.wait_time is not None]
    travels = [p.travel_time for p in delivered if p.travel_time is not None]
    totals = [p.total_time for p in delivered if p.total_time is not None]

    def _worst(metric_name: str) -> str | None:
        if not delivered:
            return None
        worst = max(delivered, key=lambda p: getattr(p, metric_name) or 0)
        value = getattr(worst, metric_name)
        return f"{worst.id} ({value} ticks)"

    return Statistics(
        wait=_summarise("wait_time", waits),
        travel=_summarise("travel_time", travels),
        total=_summarise("total_time", totals),
        delivered=len(delivered),
        requested=len(result.passengers),
        ticks=result.ticks,
        longest_wait_passenger=_worst("wait_time"),
        longest_total_passenger=_worst("total_time"),
    )


def write_positions_log(result: SimulationResult, path: str) -> None:
    """Write the per-tick elevator position log as CSV.

    Header: ``time, elevator_0, elevator_1, ...``; one row per tick.
    """
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["time"] + [f"elevator_{i}" for i in range(result.num_elevators)])
        for t, floors in enumerate(result.positions):
            writer.writerow([t] + floors)


def write_passenger_log(result: SimulationResult, path: str) -> None:
    """Write per-passenger lifecycle data as CSV (handy for plots/analysis)."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            [
                "id",
                "source",
                "dest",
                "assigned_elevator",
                "request_time",
                "pickup_time",
                "dropoff_time",
                "wait_time",
                "travel_time",
                "total_time",
            ]
        )
        for p in result.passengers:
            writer.writerow(
                [
                    p.id,
                    p.source,
                    p.dest,
                    p.assigned_elevator,
                    p.request_time,
                    p.pickup_time,
                    p.dropoff_time,
                    p.wait_time,
                    p.travel_time,
                    p.total_time,
                ]
            )


def write_summary(stats: Statistics, path: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as fh:
        fh.write(stats.render() + "\n")
