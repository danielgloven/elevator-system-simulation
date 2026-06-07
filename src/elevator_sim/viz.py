"""Optional matplotlib visualizations for a finished simulation.

Kept separate from the core so the simulation itself has no third-party
dependency. matplotlib is imported lazily inside each function, so importing
this module never fails even when matplotlib isn't installed.
"""

from __future__ import annotations

import os

from .simulation import SimulationResult
from .stats import compute_statistics


def _ensure_dir(path: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)


def plot_elevator_paths(result: SimulationResult, path: str) -> str:
    """Line chart of every car's floor over time (the position log, visually)."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    _ensure_dir(path)
    ticks = list(range(result.ticks))

    fig, ax = plt.subplots(figsize=(11, 6))
    for i in range(result.num_elevators):
        floors = [result.positions[t][i] for t in ticks]
        ax.plot(ticks, floors, linewidth=1.6, label=f"elevator_{i}", alpha=0.9)

    ax.set_title("Elevator positions over time")
    ax.set_xlabel("time (ticks)")
    ax.set_ylabel("floor")
    ax.set_ylim(0.5, result.num_floors + 0.5)
    ax.grid(True, alpha=0.25)
    ax.legend(loc="upper right")
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path


def plot_passenger_times(result: SimulationResult, path: str) -> str:
    """Stacked bar of wait + travel time per passenger, with average markers."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    _ensure_dir(path)
    delivered = [p for p in result.passengers if p.delivered]
    # Sort by total time so the chart reads as a clear distribution.
    delivered.sort(key=lambda p: p.total_time or 0)

    ids: list[str] = [p.id for p in delivered]
    waits = [p.wait_time or 0 for p in delivered]
    travels = [p.travel_time or 0 for p in delivered]
    x = range(len(delivered))

    fig, ax = plt.subplots(figsize=(11, 6))
    ax.bar(x, waits, label="wait", color="#e07a5f")
    ax.bar(x, travels, bottom=waits, label="travel", color="#3d5a80")

    stats = compute_statistics(result)
    if stats.total is not None:
        ax.axhline(
            stats.total.average,
            color="#333",
            linestyle="--",
            linewidth=1.2,
            label=f"avg total = {stats.total.average:.1f}",
        )

    ax.set_title("Per-passenger time: wait + travel (sorted by total)")
    ax.set_xlabel("passenger")
    ax.set_ylabel("ticks")
    ax.set_xticks(list(x))
    ax.set_xticklabels(ids, rotation=45, ha="right", fontsize=8)
    ax.grid(True, axis="y", alpha=0.25)
    ax.legend(loc="upper left")
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path


def plot_wait_distribution(result: SimulationResult, path: str) -> str:
    """Histograms of wait time and total time across passengers."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    _ensure_dir(path)
    delivered = [p for p in result.passengers if p.delivered]
    waits = [p.wait_time for p in delivered if p.wait_time is not None]
    totals = [p.total_time for p in delivered if p.total_time is not None]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))
    ax1.hist(waits, bins="auto", color="#e07a5f", edgecolor="white")
    ax1.set_title("Wait time distribution")
    ax1.set_xlabel("wait (ticks)")
    ax1.set_ylabel("passengers")
    ax1.grid(True, axis="y", alpha=0.25)

    ax2.hist(totals, bins="auto", color="#3d5a80", edgecolor="white")
    ax2.set_title("Total time distribution")
    ax2.set_xlabel("total (ticks)")
    ax2.grid(True, axis="y", alpha=0.25)

    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path


def render_all(result: SimulationResult, output_dir: str) -> list[str]:
    """Write every chart into ``output_dir`` and return the paths written."""
    return [
        plot_elevator_paths(result, os.path.join(output_dir, "elevator_paths.png")),
        plot_passenger_times(result, os.path.join(output_dir, "passenger_times.png")),
        plot_wait_distribution(result, os.path.join(output_dir, "time_distribution.png")),
    ]
