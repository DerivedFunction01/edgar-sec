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

- The dataset is versioned as a whole. `DATASET_NAME` and `SCHEMA_VERSION` are
  persisted: the version is written into every plan, checkpoint, and published
  artifact, and the pipeline reads it back to decide whether a stored plan is
  still loadable.
- Column order is part of the contract, not an accident: operational metadata, then
  profile columns grouped into named semantic structs, then the repeated-value columns,
  then acquisition-provenance columns from the input manifest.
- Grouping is semantic, so a field's meaning travels with it.
- Both accession forms are carried side by side in the filing struct, so a consumer
  never has to guess which spelling it was handed.
- Terminality is a closed set. `TERMINAL_STATUSES` is what the pipeline checks to
  decide a chunk checkpoint is final; a non-terminal status is not an error, it means
  the chunk is not done yet.
- The DTOs are frozen and slotted, mirror their struct field-for-field, and type the
  registrant CIK as `Cik` from `edgar_sec.domain.identity`.

**Obligations on callers.**

- Do not add a column without bumping `SCHEMA_VERSION`; the value participates in plan
  identity and in every published artifact.
- Treat `TERMINAL_STATUSES` as the completion predicate, not a validity check. A row with
  `status="partial"` is a legitimate published result.
- Use `models.py` only for in-memory work. It is not a serialization format; the Arrow
  schema is the wire contract and is what the pipeline reads and writes.

## Deliberate gaps

- **Nothing here validates a row.** There is no check that a fetched payload's keys
  match the struct fields, no migration path for an older `SCHEMA_VERSION`, and no
  identity check: a filing's accession columns are plain strings, because Arrow cannot
  hold a dataclass, so `AccessionNumber` validation happens where the value is built and
  not on read. An unrecognized key lands in `extra_fields` by convention rather than by
  an enforced rule.
