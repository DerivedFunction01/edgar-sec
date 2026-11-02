# workers

Layer 6. Pytest worker calibration and timing-profile storage.

## Purpose

Select pytest worker counts from measurements scoped to the requested tests.
Child-scope optima seed parent searches but never replace direct measurements
of the parent's combined selection; one probe runs one pytest invocation.

## Contracts

- **Aggregate profiles are independent**: Child-scope optima seed parent
  searches but never replace direct measurements of the combined selection.
- **Case timings are incremental**: Unchanged test observations survive
  inventory updates; failed, interrupted, and pruned probes are invalid.
- **Baseline pruning requires coverage**: `n=0` or `n=2` is skipped only when
  observed per-case work suffices to reject it against a direct result.
- **One pytest invocation per probe**: Mixed selections keep their selectors
  and shared session-fixture behavior.

## Deliberate gaps

- **No per-file worker allocation**: A mixed selection uses one global worker
  count; independently scheduling files at different counts is deferred.
