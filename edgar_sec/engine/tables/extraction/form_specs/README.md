# form_specs

## Purpose

The form-test stage's spec tables: the declared form-test specs aggregated by
`form_test_specs`, the measured form-signal parameters in `form_signal_specs`,
and the per-kind spec tables (composition, core form, percentage form, walk,
year ladder, AOCI claim shape).

## Contracts

- **Form tests are registry data, evaluated by one stage** (`form_tests/`):
  each kind's own parameters live in that kind's table here, keyed by
  `test_id`; a family with no declared specs has none.
- **`form_test_specs` is the aggregator**: it composes the spec tables from
  `specs/`, `separators/`, `note_separators/`, `pension/`, `seats/`, and this
  folder into the one spec set the stage evaluates.
- **Anchor labels only locate the rows the test runs over**; the test itself
  is arithmetic, and its parameters are data here, never code branches in the
  evaluator.

## Deliberate gaps

- **No evaluator lives here**: dispatch on spec kind happens only in
  `form_tests/`; this folder is read-only data at runtime.
