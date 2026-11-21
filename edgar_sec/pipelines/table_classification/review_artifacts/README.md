# Classification review artifacts

## Purpose

This package owns the persisted review-run output produced by replaying
a product fixture above the normalize line: context production plus the
classification cascade, one artifact set per run, drillable through the
CLI lane's operator surface via `adapter.ClassificationReviewAdapter`.

## Contracts

- **No re-normalization**: a run consumes stored products only; it
  never fetches a document and never calls `normalize_document`.
- **Stale is a verdict, not a run**: when the caller's expected stamps
  differ from the fixture's stamps, every case records `stale_fixture`
  and the run exits non-zero without classifying.
- **Determinism**: cases process in stable case order; manifest rows
  and per-case classification rows use stable keys (case id, table
  index).
- **Per-case isolation**: one case's failure records `execution_error`
  for that case and does not abort the run.

## Deliberate gaps

- **No expectation labels**: a run records what the cascade decides;
  adjudicated expectations and scoring belong to the measurement
  tooling, not the review run.
