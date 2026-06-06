#!/usr/bin/env python3
"""Command-line entrypoint for the elevator simulation.

Example:

    python main.py --requests data/requests.csv --elevators 3 --floors 51 \\
        --capacity 8 --strategy nearest_car --output-dir output
"""

from __future__ import annotations

import argparse
import os
import sys

# Allow running directly from the repo root without installing the package.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from elevator_sim.io_utils import load_requests
from elevator_sim.scheduler import SCHEDULERS, get_scheduler
from elevator_sim.simulation import Simulation
from elevator_sim.stats import (
    compute_statistics,
    write_passenger_log,
    write_positions_log,
    write_summary,
)


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requests", default="data/requests.csv",
                        help="path to the request CSV (time,id,source,dest)")
    parser.add_argument("--elevators", type=int, default=3,
                        help="number of elevators (default: 3)")
    parser.add_argument("--floors", type=int, default=51,
                        help="number of floors, 1-indexed (default: 51)")
    parser.add_argument("--capacity", type=int, default=8,
                        help="max passengers per elevator (default: 8)")
    parser.add_argument("--strategy", default="nearest_car", choices=sorted(SCHEDULERS),
                        help="scheduling strategy (default: nearest_car)")
    parser.add_argument("--start-floor", type=int, default=1,
                        help="floor every elevator starts on (default: 1)")
    parser.add_argument("--output-dir", default="output",
                        help="directory for log/summary files (default: output)")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)

    requests = load_requests(args.requests)
    if not requests:
        print(f"No requests found in {args.requests}", file=sys.stderr)
        return 1

    sim = Simulation(
        requests=requests,
        num_elevators=args.elevators,
        num_floors=args.floors,
        capacity=args.capacity,
        scheduler=get_scheduler(args.strategy),
        start_floor=args.start_floor,
    )
    result = sim.run()
    stats = compute_statistics(result)

    positions_path = os.path.join(args.output_dir, "positions.csv")
    passengers_path = os.path.join(args.output_dir, "passengers.csv")
    summary_path = os.path.join(args.output_dir, "summary.txt")
    write_positions_log(result, positions_path)
    write_passenger_log(result, passengers_path)
    write_summary(stats, summary_path)

    print(f"Strategy   : {args.strategy}")
    print(f"Fleet      : {args.elevators} elevators, {args.floors} floors, "
          f"capacity {args.capacity}")
    print(stats.render())
    print()
    print(f"Wrote {positions_path}")
    print(f"Wrote {passengers_path}")
    print(f"Wrote {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
