#!/usr/bin/env python3
"""Thin wrapper so the simulation can be run without installing the package:

    python main.py --requests data/requests.csv --plot

The real CLI lives in `elevator_sim.cli` (also exposed as the `elevator-sim`
console script via pyproject.toml).
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from elevator_sim.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
