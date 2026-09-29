# `edgar_sec/domain/submissions/` — The `submission_metadata` schema and its DTOs

The Phase 1 dataset contract, declared twice: once as an Arrow schema for the
Parquet artifact, once as frozen dataclasses for working in memory. Neither
representation fetches, parses, or validates the SEC payload.

## Purpose

`edgar_sec/domain/submissions/` owns the column list and nested struct types of
the `submission_metadata` dataset, and the matching dataclasses for a registrant's
profile, filings, and the aggregate of the two. It is not the parser
(`engine/submissions/`), the unroller, the builder that constructs the Arrow
arrays (`engine/submissions/builder.py`), or the pipeline that fetches and merges
them (`pipelines/metadata_sync/`).

## Layout

| Module | Responsibility |
| :--- | :--- |
| `schemas.py` | `SUBMISSION_METADATA_SCHEMA` and the six struct types it composes, plus `DATASET_NAME`, `SCHEMA_VERSION`, `TERMINAL_STATUSES` |
| `models.py` | `EntityProfile`, `SubmissionsAggregate`, `FilingRecord`, `Address`, `FormerName`, `Listing` |

## Contracts

**Guarantees this package makes.**

- The dataset is versioned as a whole. `DATASET_NAME = "submission_metadata"`
  and `SCHEMA_VERSION = "1.0.0"` are the pair that `pipelines/metadata_sync`
  writes into every plan, checkpoint, and published artifact
  (`planner.py:13`, `merger.py:19`).
- The schema is 28 top-level columns, in a fixed order: operational metadata
  first (11 columns — `cik`, `snapshot_id`, `fetched_at`, `source_url`,
  `response_sha256`, `byte_count`, `schema_version`, `status`, `error`,
  `anomalies`, `extra_fields`), then 8 profile columns grouped into named
  semantic structs, then the three repeated-value columns (`listings`,
  `filings`, `submission_files`), then 6 acquisition-provenance columns from
  the input manifest (`input_name`, `input_fingerprint`, `chunk_id`,
  `historical_files_total`, `historical_files_failed`,
  `historical_records_total`).
- Grouping is semantic, not accidental. `identity`, `classification`,
  `identifiers`, `contact`, `incorporation`, `reporting`,
  `insider_transactions`, and `addresses` are `pa.struct` values, not loose
  columns, so a field's meaning travels with it.
- Repeated SEC data is typed. `filings` is a `list_(FILING_STRUCT)` of 21
  fields; `anomalies` is a `list_(ANOMALY_STRUCT)`; `listings` and
  `submission_files` likewise. `FILING_STRUCT.items` is a `list_(string)` and
  `size` is `int64`.
- Both accession forms are carried. `FILING_STRUCT` holds
  `accession_number` and `accession_number_normalized` side by side, so a
  consumer never has to guess which one it was handed.
- Terminality is a closed set. `TERMINAL_STATUSES = {"ok", "partial",
  "failed"}` is what `pipelines/metadata_sync/worker.py:19` checks to decide a
  chunk checkpoint is final. A non-terminal status is not an error; it means the
  chunk is not yet done.
- DTOs mirror the schema field-for-field. Every field in `FILING_STRUCT` has a
  same-named field on `FilingRecord`; every field in `ADDRESS_STRUCT` has one on
  `Address`; `FORMER_NAME_STRUCT` on `FormerName`; `LISTING_STRUCT` on `Listing`.
  The DTOs are frozen and slotted, and every field is optional with a `None`
  default except `FormerName.name`, `Listing.ticker`/`exchange`, and
  `EntityProfile.cik`/`name`.
- The identity types are real value objects, not strings. `EntityProfile.cik`
  is a `Cik` and `SubmissionsAggregate.cik` is a `Cik`, both from
  `edgar_sec.domain.identity`.

**Obligations callers place on this package.**

- Do not add a column without bumping `SCHEMA_VERSION`; the value participates in
  plan identity and in every published artifact.
- Treat `TERMINAL_STATUSES` as the completion predicate, not a validity check. A
  row with `status="partial"` is a legitimate published result.
- Use `models.py` only for in-memory work. It is not a serialization format; the
  Arrow schema is the wire contract and it is what the pipeline reads and writes.

## Public surface

- `DATASET_NAME` — `"submission_metadata"`; `schemas.py:7`.
- `SCHEMA_VERSION` — `"1.0.0"`; `schemas.py:8`.
- `SUBMISSION_METADATA_SCHEMA` — the 28-column `pa.schema`; `schemas.py:83`.
- `ADDRESS_STRUCT` (10 fields), `FORMER_NAME_STRUCT` (3), `LISTING_STRUCT` (2),
  `ANOMALY_STRUCT` (3: `code`, `detail`, `source`), `FILING_STRUCT` (21),
  `SUBMISSION_FILE_STRUCT` (4: `name`, `filing_count`, `filing_from`,
  `filing_to`) — `schemas.py:10-81`.
- `TERMINAL_STATUSES` — `{"ok", "partial", "failed"}`; `schemas.py:155`.
- `Address`, `FormerName`, `Listing`, `FilingRecord`, `EntityProfile`,
  `SubmissionsAggregate` — `models.py:11-95`. `EntityProfile` carries 20 optional
  attributes plus `cik` and `name`; four of those 20 are the collections
  `former_names`, `listings`, `mailing_address`, and `business_address`.
  `SubmissionsAggregate` carries `cik`, `profile`, `filings`, `anomalies`, and
  `extra_fields`.

## Tests

```text
tests/domain/submissions/test_schemas.py    1 test function, 55 lines
```

## Deliberate gaps

- **`models.py` has no importer anywhere in the repository.** `EntityProfile`,
  `SubmissionsAggregate`, `FilingRecord`, `Address`, `FormerName`, and
  `Listing` appear in `edgar_sec/` only in their own defining module. The
  pipeline and the engine both work against the Arrow schema
  (`engine/submissions/builder.py:9` imports from `schemas.py`) and against raw
  dicts. `roadmap/refactor_v2/phase_1.md:340` records `models.py` as created in
  Milestone 1, and it remains a declared contract with no consumer — treat it as
  the in-memory shape a future caller may adopt, not as live plumbing.
- **`models.py` has no mirrored test file.** `AGENTS.md` §6.3 requires one test
  per source module; `tests/domain/submissions/test_models.py` does not exist.
  Combined with the previous point, the module is both unconsumed and unasserted.
- **`test_schemas.py` holds a single test function.** The 28-column schema, six
  struct types, and `TERMINAL_STATUSES` are pinned by one test. The transitive
  coverage is real — `tests/domain/filing_catalog/test_schemas.py:20` imports
  `SUBMISSION_METADATA_SCHEMA` and asserts the profile projection resolves — but
  the direct coverage here is thin.
- **No schema-validating code lives here.** There is no check that a fetched
  payload's keys match the struct fields, and no migration path for an older
  `SCHEMA_VERSION`. The merger validates row counts, coverage, and fingerprints;
  the engine's builder constructs the arrays. A payload with an unknown key goes
  to `extra_fields` by convention, not by a rule enforced in this package.
- **Nothing here validates identity.** `FILING_STRUCT.accession_number` is a
  plain `string`, not an `AccessionNumber`, and the Arrow schema cannot hold a
  dataclass. The `AccessionNumber` format check in
  `edgar_sec.domain.identity` runs at the edges that build the value, not on
  read.
- **The dataset name is the contract, not the directory.** This package is named
  `submissions/` (plural, describing the SEC endpoint) while the dataset it
  defines is `submission_metadata` (singular). They are deliberately different
  strings; do not unify them.
