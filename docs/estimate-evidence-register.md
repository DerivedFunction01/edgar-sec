# Estimate evidence register

The measured basis for the numeric anchors in the
supervision rules' estimates passage. An anchor with no
basis recorded here is unbacked: it is struck or marked,
never silently carried. Internal measured actuals
outrank external analogy where both exist.

## Anchors

**Minutes-per-edit (a code edit is minutes, many under
five).** Basis: internal actuals — this programme's
landed single-module edits with their tests run in
minutes end to end (a scanner module plus its test cases
through a gate cycle; a one-line regex cure with its
test file green in under two minutes of test time).
External bound: measured agent runtimes per whole
SWE-bench Verified issue run from a 66-second median
(one harness, all 500 tasks) to a 22.8-minute mean
(vendor eval harness) — an inventoried edit is a small
fraction of a whole issue. Covers: inventoried
mechanical edits (generation plus tool round-trips).
Cannot anchor: debugging, venue-bound execution.

**One-hour edit cap (migration-class edit phases).**
Basis: internal — the argument-parser
re-cut: a ~140-entry inventoried surface at
minutes-per-item prices a 15–20-item lane at or under
45 minutes of wall-clock, so a one-hour cap binds only
through the lane split, as the rule states. External:
METR's task-completion time horizons put frontier
agents' 50% horizon at roughly 50–110 human-expert
minutes (Claude 3.7 Sonnet ~50; o3 ~110) — a one-hour
agent wall-clock phase sits inside measured reliable
scope. Covers: migration-class edit phases. Cannot
anchor: novel design, research.

**Language-model-bound floor.** Basis: served output
rates for frontier models measure at roughly 50–100
tokens per second (vendor-reported serving figures), so
a generation-bound step's floor is its token volume
divided by the served rate — a measurable floor, priced
from the volume the step must produce or read. Covers:
generation- and reading-bound work only.

**Novel work and deep research.** No measured basis
exists, and none is claimed: their discipline is the
boundary test in the estimates passage (no existing
shape, failure modes not enumerable in advance;
extent not boundable in advance), which is definitional,
not numeric.

**Thirty-minute justification threshold.** Carried as
the owner's standing threshold. No measured basis is
recorded for the value itself; it is marked unbacked
here rather than given an invented one.

## Categories and their bases

**Inventoried mechanical edit — minutes per item.**
Basis: the minutes-per-edit anchor above (internal
actuals; whole-issue agent runtimes as the outer bound).

**Deterministic design and build — tens of minutes.**
Basis: internal actuals — this programme's landed
single-module builds with their tests (a scanner module
with its test file, a plan-check module) complete in
tens of minutes including gate cycles; the whole-issue
agent runtimes above bound the class from outside.
Covers design whose shape follows a pattern of record
with enumerable edge cases; it is the category the
argument-parser plan's declaration format belongs to.

**Proof run — minutes, set by the corpus and the
venue.** Basis: internal actuals — measured gate runs
(docs-scoped 7–15 s; a 282-test leg in 143 s on 2
workers; venue gates in minutes). Dummy testing and
verification runs price here.

**Coordination and fan-in — minutes to tens of
minutes.** Basis: internal actuals — union formation
and landing cycles in the programme's run records.

**Generation- or reading-bound — computed.** Basis:
the served-rate anchor above; the duration is the
volume divided by the rate, stated with the volume.

**Slow register (benchmark class) — no typical
duration; marked unbacked.** METR's horizons measure
what agents can complete at a reliability level, not a
typical duration for a step, and no internal actual
prices this class typically: its prices are argued per
step at the boundary test. The absence of a number here
is the register's honest state, not an omission.

## Sources

- METR, Task-Completion Time Horizons of Frontier AI
  Models (metr.org/time-horizons; paper: Kwa et al.,
  "Measuring AI Ability to Complete Long Software
  Tasks", NeurIPS 2025): 50% time horizons ~50 min
  (Claude 3.7 Sonnet) to ~110 min (o3), human-expert
  task durations, 170-task suite.
- SWE-bench Verified agent runtimes: myide benchmark
  (all 500 tasks, official harness): median
  agent time 66 s per task. MiniMax-M2.5 eval (vendor):
  mean end-to-end runtime 22.8 min per task at ~100
  tokens/s served output, ~3.5M tokens per task.
- DeepSWE (Datacurve; AgentField harness comparison):
  mean agent wall time 16–94 min per
  long-horizon task across ten harnesses on one model —
  harness and task mix dominate the spread, which is why
  per-edit anchors rest on internal actuals first.
- Internal actuals: the programme's gate and edit
  records (starter gate: 282 tests in
  143 s on 2 workers; docs-scoped gates 7–15 s;
  single-module cure cycles in minutes).
