# `edgar_sec/domain/submissions/` — The `submission_metadata` schema and its DTOs

The dataset contract, declared twice: once as an Arrow schema for the Parquet
artifact, once as frozen dataclasses for in-memory work. Neither representation fetches,
parses, or validates the SEC payload.

## Purpose

Owns the column list and nested struct types of the `submission_metadata` dataset, and
the matching dataclasses for a registrant's profile, filings, and the aggregate of the two.
Not the parser or the Arrow-array builder (`engine/submissions/`), and not the pipeline
that fetches and merges them (`pipelines/metadata_sync/`).

## Contracts

- **Arrow schema stability**: Dataset is versioned as a whole; `DATASET_NAME` and `SCHEMA_VERSION` are persisted into plans, checkpoints, and artifacts.
- **Column order is contract**: Operational metadata, then profile columns in semantic structs, then repeated-value columns, then acquisition-provenance columns.
- **Semantic grouping**: Field meaning travels with its semantic struct grouping.
- **Accessor forms carried**: Both accession forms are carried side-by-side in the filing struct.
- **Terminality is a closed set**: `TERMINAL_STATUSES` is what the pipeline checks; non-terminal status means chunk is not done yet.
- **Frozen DTOs**: DTOs are frozen and slotted, mirror their struct field-for-field, and type registrant CIK as `Cik`.

**Obligations on callers.**

- Do not add a column without bumping `SCHEMA_VERSION`; the value participates in plan
  identity and in every published artifact.
- Treat `TERMINAL_STATUSES` as the completion predicate, not a validity check. A row with
  `status="partial"` is a legitimate published result.
- Use `models.py` only for in-memory work. It is not a serialization format; the Arrow
  schema is the wire contract and is what the pipeline reads and writes.

## Deliberate gaps

- **No row validation**: No check that fetched payload keys match struct fields, no migration path for older `SCHEMA_VERSION`, and no identity check on read.
