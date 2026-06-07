"""Command-line entrypoint for the elevator simulation.

Run via uv:

    uv run elevator-sim --requests data/requests.csv --plot

or directly:

    python main.py --requests data/requests.csv --plot
"""

import argparse
import os
import sys
from collections.abc import Sequence

from .compare import compare_strategies, render_comparison
from .io_utils import load_requests
from .models import Request
from .scheduler import SCHEDULERS, get_scheduler
from .simulation import Simulation
from .stats import (
    compute_statistics,
    write_passenger_log,
    write_positions_log,
    write_summary,
)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Elevator system simulation")
    parser.add_argument(
        "--requests",
        default="data/requests.csv",
        help="path to the request CSV (time,id,source,dest)",
    )
    parser.add_argument("--elevators", type=int, default=3, help="number of elevators (default: 3)")
    parser.add_argument(
        "--floors", type=int, default=51, help="number of floors, 1-indexed (default: 51)"
    )
    parser.add_argument(
        "--capacity", type=int, default=8, help="max passengers per elevator (default: 8)"
    )
    parser.add_argument(
        "--strategy",
        default="nearest_car",
        choices=sorted(SCHEDULERS),
        help="scheduling strategy (default: nearest_car)",
    )
    parser.add_argument(
        "--start-floor", type=int, default=1, help="floor every elevator starts on (default: 1)"
    )
    parser.add_argument(
        "--num-express",
        type=int,
        default=0,
        help="make the last N elevators express (lobby + high floors only); needs < #elevators",
    )
    parser.add_argument(
        "--express-min-floor",
        type=int,
        default=None,
        help="lowest non-lobby floor express cars serve (required if --num-express > 0)",
    )
    parser.add_argument(
        "--output-dir", default="output", help="directory for log/summary files (default: output)"
    )
    parser.add_argument(
        "--plot", action="store_true", help="also write matplotlib charts (needs the 'viz' extra)"
    )
    parser.add_argument(
        "--compare",
        action="store_true",
        help="run every strategy on this scenario and print a comparison table",
    )
    return parser.parse_args(argv)


def _run_comparison(requests: list[Request], args: argparse.Namespace, common: dict) -> int:
    """Run every registered strategy on the same scenario and report metrics."""
    rows = compare_strategies(requests, sorted(SCHEDULERS), **common)
    table = render_comparison(rows)
    print(table)

    os.makedirs(args.output_dir, exist_ok=True)
    comparison_path = os.path.join(args.output_dir, "comparison.txt")
    with open(comparison_path, "w") as fh:
        fh.write(table + "\n")
    print(f"\nWrote {comparison_path}")

    if args.plot:
        try:
            from .viz import plot_strategy_comparison
        except ImportError:
            print("\nmatplotlib not available; install with: uv sync --extra viz", file=sys.stderr)
            return 1
        chart = plot_strategy_comparison(
            rows, os.path.join(args.output_dir, "strategy_comparison.png")
        )
        print(f"Wrote {chart}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)

    requests = load_requests(args.requests)
    if not requests:
        print(f"No requests found in {args.requests}", file=sys.stderr)
        return 1

    common = {
        "num_elevators": args.elevators,
        "num_floors": args.floors,
        "capacity": args.capacity,
        "start_floor": args.start_floor,
        "num_express": args.num_express,
        "express_min_floor": args.express_min_floor,
    }

    if args.compare:
        return _run_comparison(requests, args, common)

    sim = Simulation(requests=requests, scheduler=get_scheduler(args.strategy), **common)
    result = sim.run()
    stats = compute_statistics(result)

    positions_path = os.path.join(args.output_dir, "positions.csv")
    passengers_path = os.path.join(args.output_dir, "passengers.csv")
    summary_path = os.path.join(args.output_dir, "summary.txt")
    write_positions_log(result, positions_path)
    write_passenger_log(result, passengers_path)
    write_summary(stats, summary_path)

    print(f"Strategy   : {args.strategy}")
    fleet = f"{args.elevators} elevators, {args.floors} floors, capacity {args.capacity}"
    if args.num_express:
        fleet += f" ({args.num_express} express >= floor {args.express_min_floor})"
    print(f"Fleet      : {fleet}")
    print(stats.render())
    print()
    print(f"Wrote {positions_path}")
    print(f"Wrote {passengers_path}")
    print(f"Wrote {summary_path}")

    if args.plot:
        try:
            from .viz import render_all
        except ImportError:
            print("\nmatplotlib not available; install with: uv sync --extra viz", file=sys.stderr)
            return 1
        for chart in render_all(result, args.output_dir):
            print(f"Wrote {chart}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
