"""Run several scheduling strategies on the same scenario and tabulate metrics.

This is what powers the "fairness vs efficiency" discussion: each strategy is
run against an identical request stream and building, then summarised on a few
axes:

* **efficiency** - average total time (wait + travel) per passenger;
* **fairness**   - the *worst* wait time (the most-starved passenger);
* **throughput** - makespan, i.e. how many ticks until everyone is delivered.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from .models import Request
from .scheduler import get_scheduler
from .simulation import Simulation
from .stats import compute_statistics


@dataclass
class StrategyMetrics:
    """One row of the comparison table."""

    strategy: str
    avg_wait: float
    max_wait: int
    avg_total: float
    max_total: int
    makespan: int
    delivered: int


def compare_strategies(
    requests: Sequence[Request],
    strategy_names: Sequence[str],
    **sim_kwargs: object,
) -> list[StrategyMetrics]:
    """Run each named strategy on the same scenario and return their metrics."""
    rows: list[StrategyMetrics] = []
    for name in strategy_names:
        # Fresh scheduler each run (some, e.g. round_robin, carry state).
        sim = Simulation(requests, scheduler=get_scheduler(name), **sim_kwargs)  # type: ignore[arg-type]
        stats = compute_statistics(sim.run())
        rows.append(
            StrategyMetrics(
                strategy=name,
                avg_wait=stats.wait.average if stats.wait else 0.0,
                max_wait=stats.wait.maximum if stats.wait else 0,
                avg_total=stats.total.average if stats.total else 0.0,
                max_total=stats.total.maximum if stats.total else 0,
                makespan=stats.ticks,
                delivered=stats.delivered,
            )
        )
    return rows


def render_comparison(rows: Sequence[StrategyMetrics]) -> str:
    """Format the comparison rows as an aligned text table."""
    header = (
        f"{'strategy':<14}{'avg_wait':>10}{'max_wait':>10}"
        f"{'avg_total':>11}{'max_total':>11}{'makespan':>10}{'delivered':>11}"
    )
    lines = ["=" * len(header), "STRATEGY COMPARISON", "=" * len(header), header, "-" * len(header)]
    for r in rows:
        lines.append(
            f"{r.strategy:<14}{r.avg_wait:>10.1f}{r.max_wait:>10}"
            f"{r.avg_total:>11.1f}{r.max_total:>11}{r.makespan:>10}{r.delivered:>11}"
        )
    lines.append("=" * len(header))
    return "\n".join(lines)
