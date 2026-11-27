# xbrl_eval

Layer 6. XBRL census, screening, and benchmark verification.

## Purpose

Score grounded XBRL populations through the client facade and adjudicate
results as JSON. Its evaluation runners all read archived cohorts and bundles;
none fetch remotely.

## Contracts

- **Offline evaluation**: All runners read archived cohorts and fixture
  bundles; no runner performs network I/O.
- **Facade-scored populations**: Census populations are produced through the
  client facade, never by re-implementing query semantics.
- **JSON adjudication**: Battery and benchmark outcomes record per-filing
  check outcomes as JSON.
- **Probe registry home**: `probe_cohort.json` lives in this package, homed
  with the tools plane that consumes it; `pipelines.xbrl_review.cohort`'s
  `canonical_probe_cohort_path` resolves it, and an external corpus root's
  `review/` copy wins when present.

## Deliberate gaps

- **No artifact production**: Seeding linkbases and building taxonomy slices
  belong to `xbrl_discovery`.
