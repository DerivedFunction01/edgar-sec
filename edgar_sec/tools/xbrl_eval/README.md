# xbrl_eval

Layer 6. XBRL census, screening, and benchmark verification.

## Purpose

Score grounded XBRL populations through the client facade and adjudicate
results as JSON. Census, screen, facade battery, token-coverage audit, and
lattice mining all read archived cohorts and bundles; none fetch remotely.

## Contracts

- **Offline evaluation**: All runners read archived cohorts and fixture
  bundles; no runner performs network I/O.
- **Facade-scored populations**: Census populations are produced through the
  client facade, never by re-implementing query semantics.
- **JSON adjudication**: Battery and benchmark outcomes record per-filing
  check outcomes as JSON.

## Deliberate gaps

- **No artifact production**: Seeding linkbases and building taxonomy slices
  belong to `xbrl_discovery`.
