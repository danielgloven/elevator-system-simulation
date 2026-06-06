# Elevator System Simulation

A discrete-time simulation of a modern **Destination Dispatch** elevator system.
Passengers declare both their origin *and* destination at request time; the
controller immediately and permanently assigns each request to a specific
elevator, then the fleet serves everyone while minimising time per passenger.

## Objectives (from the brief)

1. **Serve all requests eventually** — no passenger waits forever.
2. **Minimise total time per passenger**, where `total_time = wait_time + travel_time`.
3. **Honor elevator constraints** — capacity and direction logic.

## How to Run

Requires **Python 3.8+** (developed on 3.9). The core simulation has **no
third-party dependencies**.

```bash
# Run with the bundled sample requests and sensible defaults
python main.py --requests data/requests.csv

# Configure the building and the scheduler
python main.py \
    --requests data/requests.csv \
    --elevators 3 \
    --floors 51 \
    --capacity 8 \
    --strategy nearest_car \
    --output-dir output
```

CLI options:

| Flag             | Default            | Meaning                                   |
| ---------------- | ------------------ | ----------------------------------------- |
| `--requests`     | `data/requests.csv`| Input CSV (`time,id,source,dest`)         |
| `--elevators`    | `3`                | Number of elevator cars                   |
| `--floors`       | `51`               | Number of floors (1-indexed, ground = 1)  |
| `--capacity`     | `8`                | Max simultaneous passengers per car       |
| `--strategy`     | `nearest_car`      | `nearest_car` or `round_robin`            |
| `--start-floor`  | `1`                | Floor every car starts on                 |
| `--output-dir`   | `output`           | Where logs/summary are written            |

### Running the tests

```bash
pip install -r requirements.txt   # installs pytest
python -m pytest -q
```

## Input Format

A CSV with a header row. Each subsequent row is one request:

```csv
time,id,source,dest
0,passenger1,1,51
0,passenger2,1,37
10,passenger3,20,1
```

* `time` — integer tick the request is made
* `id` — unique passenger id
* `source` — origin floor
* `dest` — destination floor

The engine only ever reads requests for the **current** tick — it never peeks
ahead in the request list.

## Outputs

Written to `--output-dir` (default `output/`, git-ignored):

* **`positions.csv`** — the required elevator position log: one row per tick,
  one column per elevator (`time, elevator_0, elevator_1, ...`).
* **`passengers.csv`** — per-passenger lifecycle (request/pickup/dropoff times
  and derived wait/travel/total times); useful for analysis and plots.
* **`summary.txt`** — the passenger summary statistics (also printed to stdout):
  min / max / average of **wait**, **travel**, and **total** time, plus
  observations (delivered count, run length, worst-case passengers).

Example summary:

```
PASSENGER SUMMARY STATISTICS
========================================================
wait_time    min=   0  max=  88  avg=  31.80  (n=10)
travel_time  min=  20  max=  85  avg=  50.30  (n=10)
total_time   min=  37  max= 135  avg=  82.10  (n=10)
--------------------------------------------------------
Passengers delivered : 10 / 10
Simulation length    : 158 ticks
```

## Design Overview

The code is split so that *what gets decided* is separate from *how the cars
move* and *when things happen*:

| Module             | Responsibility                                              |
| ------------------ | ---------------------------------------------------------- |
| `models.py`        | `Request`, `Passenger`, `Elevator` (movement + LOOK route) |
| `scheduler.py`     | Pluggable assignment policies (which car gets a request)   |
| `simulation.py`    | The discrete-time tick loop / engine                       |
| `stats.py`         | Summary statistics + output writers                        |
| `io_utils.py`      | Request CSV loading                                        |
| `main.py`          | CLI wiring                                                 |

**Time model.** Discrete ticks; one tick = one floor of travel. A stop costs
one extra **dwell** tick during which passengers board/alight.

**Each tick:** release requests timestamped *now* → assign each to a car →
every car either services its floor (dwell) or moves one floor along its route →
log all positions.

**Movement.** Each car uses the **LOOK** ("elevator algorithm") scan: keep going
in the current direction serving every stop, then reverse when nothing remains
ahead. A car's stops are the destinations of its onboard passengers plus the
source floors of passengers assigned to it but not yet aboard.

**Scheduling.** The default `nearest_car` strategy assigns each request to the
car that can reach the pickup floor soonest (direction-aware), with a light
load-balancing penalty so work spreads across the fleet. `round_robin` is a
naive baseline. New strategies implement one method and register themselves —
the engine never changes.

See **[DECISIONS.md](DECISIONS.md)** for the full reasoning, trade-offs, and a
walkthrough of likely follow-up questions.

## Assumptions, Simplifications & Trade-offs

A short list (full detail in DECISIONS.md):

* Floors are **1-indexed** (ground = 1); the sample data goes up to floor 51.
* **Dwell = 1 tick per stop** regardless of how many people board/alight.
* Boarding/alighting are **instantaneous within** that dwell tick.
* A passenger's car assignment is **fixed at request time** (true Destination
  Dispatch) and never reassigned, even if a better car becomes available.
* If a car arrives at a pickup while **full**, the waiting passenger stays
  assigned and is collected on a later pass — never dropped.
* The `nearest_car` cost is a cheap **estimate**, not a full route re-simulation.

## Time Spent

_~__ hours_ (to be filled in).

## What I'd Improve With More Time

* **Bonus schedulers**: zone-based dispatch and express elevators (the
  architecture already supports dropping these in).
* **Visualization**: matplotlib charts (wait-time distribution, elevator paths
  over time) for the presentation.
* **Smarter dispatch**: cost based on a real route re-simulation, and optional
  re-assignment when a much closer car frees up.
* **Richer realism**: per-floor dwell proportional to people moved, idle-car
  "parking" heuristics, and a fairness-vs-efficiency tuning knob.
* A scenario generator + batch comparison harness to benchmark strategies.
