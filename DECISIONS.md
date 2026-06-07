# Design Decisions

This document records the interesting decisions behind the simulation and the
trade-offs each one carries. The README is the user-facing doc.

---

## 1. The big modeling choices

### 1.1 Discrete event loop, fixed tick order

The simulation advances one tick at a time. Within each tick the order is fixed
and deliberate:

1. **Release** requests timestamped for *this* tick (never look further ahead).
2. **Assign** each new passenger to a car (scheduler decides).
3. **Move or service** every car by one tick.
4. **Log** all car positions.

**Why this order:** releasing before assigning means a request is assignable the
instant it arrives. Assigning before moving means a brand-new request can
influence a car that is about to move this very tick (no artificial one-tick lag
on assignment). Logging last means the log reflects the position *after* the
tick's action, which is the intuitive "where is the car now" reading.

**Trade-off:** a strict per-tick loop is simple and easy to reason about / test,
but it is O(ticks × elevators). For a giant building with sparse traffic an
event-driven loop (jump straight to the next interesting tick) would be faster.
For the scale here, clarity wins.

### 1.2 Time units: 1 tick = 1 floor, plus a 1-tick dwell per stop

The brief fixes "one time unit = one floor of travel." I added a **1-tick dwell**
at each stop (doors open, people move). This was an explicit choice (it could
have been zero):

* **Pro:** more realistic — stopping genuinely costs time, so a scheduler that
  makes fewer/closer stops is rewarded. It makes the wait-vs-travel trade-off
  visible in the numbers.
* **Con:** dwell is flat (1 tick whether 1 or 8 people move). A real building's
  dwell scales with boardings. Documented as a simplification; easy to extend.

Boarding and alighting happen **within** the dwell tick (alight first, then
board). Pickup/drop-off timestamps are stamped at that tick.

### 1.3 Floors are 1-indexed (ground = 1)

The sample data references floors up to 51 and down to 1, never 0. Buildings are
described "floor 1..N," so I model floors as `1..num_floors` and start cars at
floor 1. Validation rejects any source/dest outside that range. (A 0-indexed
model would work too; this just matches the data and human intuition.)

### 1.4 What "total time" means here

`total_time = wait_time + travel_time` where:

* `wait_time = pickup_time − request_time` (how long until the doors first open
  for you),
* `travel_time = dropoff_time − pickup_time` (time aboard, **including** dwell
  ticks at intermediate stops and the dwell tick where you alight).

This matches the brief's formula and is what every statistic is computed from.

---

## 2. Movement: the LOOK / "elevator algorithm"

Each car keeps a set of target floors = `{destinations of onboard passengers} ∪
{source floors of assigned-but-waiting passengers}`. It serves them with **LOOK**:
continue in the current direction, serving every target along the way; when
nothing remains ahead, reverse toward the nearest target behind.

**Why LOOK over alternatives:**

* vs. **FCFS (serve in request order):** FCFS causes wild back-and-forth and
  starves throughput. LOOK is the classic, well-understood elevator scan.
* vs. **SCAN (go all the way to the end floor):** LOOK reverses as soon as there
  are no more requests ahead, so it doesn't waste travel to the top/bottom.

**The capacity subtlety (important):** a full car must not get stuck dwelling
forever at a pickup floor it can't satisfy. So "should I open doors here?" is:
*there's a drop-off here* **or** *there's a pickup here and I have room*. A full
car therefore skips a pickup-only floor, continues to a drop-off, frees a seat,
and the LOOK scan naturally brings it back. That floor stays in the target set
the whole time, which is what guarantees the passenger is eventually served.

---

## 3. Scheduling: pluggable, `nearest_car` by default

### 3.1 Why a Scheduler interface

Assignment policy is the part most likely to change (the brief's bonus literally
asks for several). So it's isolated behind a one-method base class with a name
registry. `simulation.py` and `models.py` never change when a strategy is added.
This is the Strategy pattern, and it's what makes the bonus work incremental.

### 3.2 `nearest_car` cost function

For each car, estimate ticks-to-reach the passenger's source:

* **Idle car:** straight-line distance `|pos − source|`.
* **Source ahead** on the car's current direction: distance directly to it.
* **Source behind** the car's direction: it must run out its current direction
  to its furthest committed stop, then come back — cost is that two-leg path.
* Plus a **load penalty** (`2.0 × (onboard + waiting)`) so a slightly closer but
  overloaded car doesn't hoard every request.

The car with the lowest cost wins; assignment is then **final**.

**The load-penalty tuning story.** I first set the penalty
to `0.5`. On a burst *lobby rush* (most requests originate at floor 1) that was
pathological: the "nearest" car is the *same* car for everyone, and a 0.5 penalty
never outweighed the floor-distance term, so the whole rush piled onto one car
while the others idled — `round_robin` (which blindly spreads load) beat it
soundly. Raising the penalty to **2.0** cut the rush scenario's average total
time ~26% (117 → 86 ticks) and makespan from 291 → 206, with **no regression** on
lighter scenarios. Lesson: greedy "nearest" needs a real load-balancing term
once origins are correlated.

**Trade-off:** the cost is still a cheap *estimate*, not a full route
re-simulation. A higher-fidelity version would simulate inserting the new stops
into each car's route and score the actual resulting times — more accurate, more
expensive, and the natural next step.

### 3.3 `zone_based` scheduler (bonus)

Split the building into contiguous bands, one per car; assign a request to the
car whose zone owns its **source** floor (falling back to the nearest eligible
zone if the owner is, e.g., an express car that can't serve the trip). The
appeal is **locality** — a car stays near its zone, so it's usually close to its
next pickup, and it's naturally fair *within* a zone.

**Trade-off (and what the data shows):** zoning dies under **skewed demand**. In
the lobby rush almost every request originates on floor 1, which lives in car 0's
zone — so car 0 is slammed while cars 1–2 sit idle. It's the worst performer on
that scenario by a wide margin (see §6). Zoning shines when demand is spread
across floors (e.g. steady inter-floor traffic), not during a correlated rush.

### 3.4 `round_robin` baseline

Strict rotation, position-ignorant. It exists to (a) prove the interface is
genuinely pluggable and (b) give a baseline. Surprisingly, under a pure lobby
rush its blind even-spreading is *hard to beat* — see the comparison in §3.6.

### 3.5 Express elevators (bonus)

An express car serves only a subset of floors — modeled as an optional
`serviceable_floors` set on `Elevator` (`None` = serves everything). The CLI
exposes a "sky-lobby" style: the last N cars serve the **lobby plus floors at or
above `express_min_floor`**, skipping the low/mid floors.

**Key design choice — feasibility lives in the engine, not the scheduler.** The
tick loop filters the fleet to cars that can serve a given request *before*
calling the scheduler, so every scheduler automatically respects express
constraints and none of them needed to change. We also require **≥ 1 standard
car**, which guarantees every request is always serviceable (no passenger can be
stranded by an all-express fleet). Tested in `test_bonus.py`
(`test_express_serves_everyone_and_respects_constraints`).

### 3.6 Strategy comparison results (fairness vs efficiency)

Run `uv run elevator-sim --requests data/rush_hour.csv --compare`. On the bundled
31-passenger lobby-rush scenario (3 cars, 51 floors, capacity 8):

**Scenario A — lobby rush** (`data/rush_hour.csv`): most origins at floor 1.

| strategy      | avg wait | max wait | avg total | makespan |
| ------------- | -------- | -------- | --------- | -------- |
| `nearest_car` |   49.6   |   130    |   86.4    |   206    |
| `round_robin` |   45.6   |    96    |   83.6    |   155    |
| `zone_based`  |   96.5   |   235    |  134.3    |   318    |

**Scenario B — spread inter-floor traffic** (`data/inter_floor.csv`): origins and
destinations uniform across all 51 floors.

| strategy      | avg wait | max wait | avg total | makespan |
| ------------- | -------- | -------- | --------- | -------- |
| `nearest_car` |   30.5   |   108    |   66.3    |   177    |
| `round_robin` |   40.7   |   103    |   80.1    |   167    |
| `zone_based`  |   34.5   |   147    |   69.4    |   180    |

**The headline: the two scenarios invert the ranking.** That's the whole point.

* **Efficiency** = avg total; **fairness** = max wait (worst-served passenger).
* **Lobby rush → `round_robin` wins** (counter-intuitively). When every origin is
  floor 1, every car is equally good, so "spread blindly" is near-optimal and
  greedy "nearest" only risks imbalance. `zone_based` is worst — the rush
  concentrates all origins in one car's zone (textbook zoning failure).
* **Inter-floor → `nearest_car` wins** (~17% lower avg total than `round_robin`),
  and `zone_based` also beats `round_robin`. With origins spread out, "nearest" is
  genuinely informative and zoning's locality finally pays off.
* Note the nuance even in B: `round_robin` still has the tightest *makespan* and
  *max_total* — blind spreading keeps the tail tight while losing on the average.
* General lesson: **the best scheduler depends on the traffic pattern.** No policy
  wins everywhere. A real system would detect the regime (up-peak vs. inter-floor
  vs. down-peak) and switch — this is the single most compelling "what's next."
* This finding is locked in by `test_best_strategy_depends_on_traffic_pattern`.

---

## 4. How the objectives are guaranteed

| Objective | How it's met |
| --- | --- |
| **Serve everyone eventually** | A passenger's source/dest stay in their car's target set until actually served; LOOK always returns to remaining targets; the run loop only ends when `delivered == requested`. Tested in `test_every_passenger_is_eventually_delivered`. |
| **Minimise total time** | LOOK avoids wasteful travel; `nearest_car` minimises estimated pickup time; the load penalty prevents pile-ups. |
| **Honor constraints** | Capacity enforced at boarding (`is_full` check); a full car never exceeds capacity (tested in `test_capacity_is_never_exceeded`); direction handled by LOOK. |

A `max_ticks` safety bound raises if the loop ever runs absurdly long — a guard
that turns an infinite-loop bug into a clear error instead of a hang.

---

## 5. Reading the visualizations

Generated with `uv run elevator-sim --plot` on the bundled sample (3 elevators,
51 floors, capacity 8, `nearest_car`).

### 5.1 `elevator_paths.png` — the "elevator diagram"

Floor vs. time, one line per car. The whole run is legible at a glance:

* All three cars **surge upward together** early on — five of the ten sample
  passengers originate at floor 1 (a morning-lobby rush), so the scheduler
  loads the lobby and sends everyone up.
* They **peak around floors 45–51**, then **descend** to serve the down-traffic
  (e.g. passenger3 20→1, passenger5 40→2, passenger9 51→1).
* The **flat tails** at the end are cars parking after their final drop-off (no
  remaining work → `IDLE`).
* The tiny **stair-steps** in the lines are the 1-tick dwells at each stop.

This is literally the contents of `positions.csv` made visual — the scheduler's
macro behavior matches the traffic pattern.

### 5.2 `passenger_times.png` — wait + travel, stacked, sorted by total

Orange = wait, blue = travel; dashed line = average total (~82 ticks).

* The orange-vs-blue split **is** the fairness-vs-efficiency story made concrete.
* Passengers **6, 8, and 10 have huge wait components** — they requested
  *mid-rush* (t=15, 22, 30) while all three cars were already committed upward,
  so they sat until a car came back. That is the **known weakness of greedy
  `nearest_car` with fixed assignment**: a request that arrives just after the
  fleet commits elsewhere has no nearby car and can't be re-assigned.
* Passengers near the left (e.g. passenger2, passenger1) have **near-zero wait**
  — a car was already heading their way.

This leads straight into "what I'd improve" — re-assignment when a closer car
frees up, or a wait-aware cost term that penalizes leaving an old request stranded.

### 5.3 `time_distribution.png` — wait & total histograms

* The **wait histogram is bimodal**: a cluster near 0 (lucky passengers a car
  was already approaching) and a second cluster at ~70–88 (the mid-rush starved
  ones). Two populations, not one smooth spread.
* This is why **average alone is misleading** — avg wait ~32 hides the fact that
  nobody actually waited ~32; people waited either ~5 or ~80. It motivates
  reporting **tail/worst-case** metrics (max wait) alongside the mean, and is
  exactly the fairness lever the bonus asks about.

### 5.4 The one-sentence version

"Greedy nearest-car is efficient on average but produces a **bimodal, unfair**
wait distribution under bursty lobby traffic; the fix is re-assignment and a
wait-aware cost term — which the pluggable scheduler interface is built to allow."

---

## 6. Assumptions & simplifications (the honest list)

* Dwell is a flat 1 tick regardless of how many people move.
* Boarding/alighting are instantaneous within the dwell tick.
* Assignment is fixed at request time — no re-assignment if a better car later
  frees up (true Destination Dispatch, but leaves optimization on the table).
* The `nearest_car` cost is an estimate, not an exact route cost.
* All cars are identical (same capacity, same speed, can serve any floor).
* No physical acceleration/deceleration; constant 1 floor/tick.
* Requests are trusted/valid (source ≠ dest, floors in range — validated, not
  sanitized beyond that).

---

## 7. Anticipated questions (and answers)

**Q: Why discrete time instead of a continuous/event-driven simulation?**
The brief mandates ticking one unit at a time and not peeking ahead, so discrete
time is the natural fit and keeps the model transparent and testable. For larger
scale I'd move to an event queue that jumps to the next interesting time.

**Q: How do you guarantee no starvation?**
A passenger's pickup floor remains in their assigned car's target set until they
board, and their destination remains until they alight. LOOK always eventually
returns to any remaining target, and the simulation doesn't terminate until
everyone is delivered. There's no path where a passenger is forgotten — even a
repeatedly-full car frees seats as it makes drop-offs and the scan brings it
back.

**Q: What happens when an elevator is full and reaches a waiting passenger?**
It doesn't open for them (capacity check in `should_service_here`). It continues
to a drop-off, frees a seat, and returns on a later pass. The passenger is never
dropped from the plan.

**Q: Why fix the assignment at request time? Couldn't you do better by
re-assigning?**
Fixing it is the definition of Destination Dispatch and keeps the system
predictable (a passenger is told their car immediately). Yes, allowing
re-assignment when a much closer car frees up would lower average times — I list
it under future work. It adds complexity (and can hurt the perceived fairness of
"you were told car B").

**Q: How would you add the express-elevator bonus?**
Give each elevator a `serviceable_floors` set; the scheduler skips cars that
can't serve a request's source or dest, and LOOK only routes to serviceable
targets. A zone-based scheduler is similar: partition floors into zones and bias
assignment toward the car that owns the request's zone. Both are new schedulers /
small `Elevator` attributes — no engine changes.

**Q: How do you trade fairness against efficiency?**
Efficiency = minimise average total time (favours batching along the majority
flow). Fairness = bound the *worst* wait (no one starves). The load penalty in
`nearest_car` is a small lever toward fairness. A tunable weight between "average
total time" and "max wait" in the cost function would make the trade-off
explicit — good material for the comparison write-up.

**Q: How is this tested?**
`tests/test_simulation.py` covers: eventual delivery, the causal ordering
`request ≤ pickup ≤ dropoff`, capacity never exceeded, no peek-ahead (a late
request can't be served early), determinism (same input → same positions), a
hand-computed single-passenger stat, the LOOK direction rule, and that every
scheduler serves everyone.

**Q: What's the computational complexity?**
Per tick: O(elevators × passengers-on-that-car) for routing/servicing, plus
O(elevators) for assignment per new request. Overall roughly
O(ticks × elevators × avg_load). Fine for the stated scale (1–10 cars). Bottleneck
at large scale would be the per-tick scan; an event-driven loop fixes it.

**Q: If you had one more day, what's the highest-value addition?**
The zone-based + express schedulers and a small batch harness that runs every
strategy on the same scenarios and tabulates the stats — that directly answers
the "fairness vs efficiency" bonus and makes for a compelling demo.

---

## 8. Engineering practices & tooling

These aren't required by the brief, but they're the difference between "a script"
and "a maintainable project."

* **uv** for environment + dependency management — fast, reproducible
  (`uv.lock` pins exact versions), and it provisions the right Python itself.
* **src/ layout** — the package lives under `src/elevator_sim/`, so tests run
  against the *installed* package, not loose files. Prevents "works because the
  file happens to be in the cwd" bugs.
* **Ruff** for linting + formatting — one fast tool replacing black + flake8 +
  isort. Enforces style and catches bug-prone patterns (bugbear, comprehensions).
* **pytest + coverage** — 34 tests, coverage gated at **85%** in
  `pyproject.toml` (currently ~94%). The gate means new untested code fails CI,
  not just looks bad in a report. `viz.py` is excluded from the gate (it's
  exercised by the smoke run, and asserting on pixels is low-value).
* **mypy** static type checking — verifies the type hints throughout the code
  (config in `pyproject.toml`, matplotlib's missing stubs ignored). Catches a
  class of bugs before runtime. Runs in CI and pre-commit.
* **Security scanning** — two complementary tools: **bandit** (SAST over our own
  code, looking for insecure patterns) and **pip-audit** (checks dependencies
  against the CVE advisory DB). Both run in CI and as pre-commit hooks.
* **GitHub Actions CI** — a `test` matrix across **Python 3.12–3.13** plus a
  `quality` job (ruff + mypy + bandit + pip-audit). Green checks show on the
  public repo before anyone reads the code.
* **pre-commit hooks** — ruff/mypy/bandit/whitespace run automatically before
  each commit, so the same gates that run in CI run locally first. Fast feedback,
  nothing broken ever gets pushed.
* **MIT LICENSE** — explicit permissive license, expected on a public repo that's
  meant to be cloned and run.

### Python version: 3.12 floor (and why we *removed* `from __future__ import annotations`)

Earlier the project declared a 3.9 floor and carried `from __future__ import
annotations` in every module. That import makes annotations **lazy** (stored as
strings, PEP 563), which let the modern `list[int]` / `int | None` hint syntax
(PEP 585 / 604) run on Python 3.9 even though that syntax otherwise needs 3.10+.

We then chose to **bump the floor to Python 3.12** and drop the future imports.
Rationale:

* uv already runs us on 3.12, and there's no requirement to support older
  Pythons for this project — so the portability the future import bought us
  wasn't worth carrying.
* On 3.12 the modern hint syntax is **native**, so the imports became pure
  boilerplate. Removing them is less code and one fewer thing to explain.
* 3.12 is current and well-supported by all our deps.

Trade-off: the code no longer runs on 3.9–3.11. That's an explicit, acceptable
choice here. If broad compatibility were a goal, the alternative is exactly what
we had before — keep `requires-python = ">=3.9"` and the future imports. (Good
thing to be able to articulate: the future import is the bridge that decouples
"modern annotation syntax" from "minimum Python version.")

---

## 9. Changelog of decisions

* **v0.1 (first pass):** core engine, LOOK movement, `nearest_car` (default) +
  `round_robin`, full stats + CSV outputs, test suite. Bonus schedulers and
  express elevators intentionally deferred to keep the first pass focused and
  working end-to-end.
* **v0.2:** project moved to **uv** (`pyproject.toml`, dependency groups,
  `elevator-sim` console script); core stays stdlib-only with matplotlib/pytest
  as managed dev deps. Added **matplotlib visualizations** (`viz.py`, `--plot`):
  elevator paths over time, per-passenger wait+travel stacked bars, and
  wait/total histograms. The sample run surfaces a bimodal wait distribution
  (lucky vs. mid-rush-starved passengers) — concrete fodder for the
  fairness-vs-efficiency discussion. Bonus schedulers still pending.
* **v0.3:** added engineering tooling — Ruff (lint+format), pytest coverage gate
  (85%), bandit + pip-audit security scanning, GitHub Actions CI (Python
  3.9–3.12 matrix + quality job), and pre-commit hooks. Added tests for io/stats/
  CLI to lift coverage to ~95%. Modernized type-hint syntax (kept
  `from __future__ import annotations` so it still runs on 3.9). Bonus schedulers
  still pending.
* **v0.4:** **bumped the Python floor to 3.12** and removed all
  `from __future__ import annotations` (native modern syntax on 3.12); CI matrix
  narrowed to 3.12–3.13. Added **mypy** type checking (CI + pre-commit) and an
  **MIT LICENSE**. Committed **sample charts in `docs/`** so they render on the
  GitHub page (kept in sync with `viz.py` output). Bonus schedulers still pending.
* **v0.5 (bonuses):** added the **`zone_based`** scheduler and **express
  elevators** (engine-enforced feasibility, sky-lobby model). New **comparison
  harness** (`compare.py`, `--compare`) + grouped-bar comparison chart, plus a
  bundled `data/rush_hour.csv` lobby-rush scenario. Tuned `nearest_car`'s load
  penalty 0.5 → 2.0 after the rush exposed a pile-onto-one-car failure mode.
  Documented the fairness-vs-efficiency findings (§3.6). 34 tests, ~94% coverage.
* **v0.6:** added a second scenario `data/inter_floor.csv` (spread traffic) that
  **inverts** the strategy ranking vs. the lobby rush — concrete proof that the
  best scheduler depends on traffic pattern. Added a regression test locking in
  the contrast and a second comparison chart. No engine changes (data + docs).
