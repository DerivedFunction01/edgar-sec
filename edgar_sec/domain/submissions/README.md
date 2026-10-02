# `edgar_sec/domain/submissions/` — The `submission_metadata` schema and its DTOs

The Phase 1 dataset contract, declared twice: once as an Arrow schema for the Parquet
artifact, once as frozen dataclasses for in-memory work. Neither representation fetches,
parses, or validates the SEC payload.

## Purpose

Owns the column list and nested struct types of the `submission_metadata` dataset, and
the matching dataclasses for a registrant's profile, filings, and the aggregate of the two.
Not the parser or the Arrow-array builder (`engine/submissions/`), and not the pipeline
that fetches and merges them (`pipelines/metadata_sync/`).

## Layout

| Module | Responsibility |
| :--- | :--- |
| `schemas.py` | `SUBMISSION_METADATA_SCHEMA` and the six struct types it composes, plus `DATASET_NAME`, `SCHEMA_VERSION`, `TERMINAL_STATUSES` |
| `models.py` | `EntityProfile`, `SubmissionsAggregate`, `FilingRecord`, `Address`, `FormerName`, `Listing` |

## Contracts

- The dataset is versioned as a whole. `DATASET_NAME = "submission_metadata"` and
  `SCHEMA_VERSION = "1.0.0"`; `SCHEMA_VERSION` is imported by `metadata_sync/planner.py`
  and `merger.py` and written into every plan, checkpoint, and published artifact.
- The schema is 28 top-level columns in a fixed order: 11 operational metadata columns
  (`cik` … `extra_fields`), then 8 profile columns grouped into named semantic structs,
  then the three repeated-value columns (`listings`, `filings`, `submission_files`), then
  6 acquisition-provenance columns from the input manifest.
- Grouping is semantic, not accidental. `identity`, `classification`, `identifiers`,
  `contact`, `incorporation`, `reporting`, `insider_transactions`, and `addresses` are
  `pa.struct` values, so a field's meaning travels with it.
- Repeated SEC data is typed. `filings` is a `list_(FILING_STRUCT)` of 21 fields;
  `FILING_STRUCT.items` is a `list_(string)` and `size` is `int64`.
- Both accession forms are carried. `FILING_STRUCT` holds `accession_number` and
  `accession_number_normalized` side by side, so a consumer never has to guess which one
  it was handed.
- Terminality is a closed set. `TERMINAL_STATUSES = {"ok", "partial", "failed"}` is what
  `pipelines/metadata_sync/worker.py` checks to decide a chunk checkpoint is final. A
  non-terminal status is not an error; the chunk is not yet done.
- DTOs mirror the schema field-for-field. Every field in `FILING_STRUCT`,
  `ADDRESS_STRUCT`, `FORMER_NAME_STRUCT`, and `LISTING_STRUCT` has a same-named field on
  the corresponding dataclass. The DTOs are frozen and slotted, and every field is
  optional with a `None` default except `FormerName.name`, `Listing.ticker`/`exchange`,
  and `EntityProfile.cik`/`name`.
- The identity types are real value objects: `EntityProfile.cik` and
  `SubmissionsAggregate.cik` are `Cik`, from `edgar_sec.domain.identity`.

**Obligations on callers.**

- Do not add a column without bumping `SCHEMA_VERSION`; the value participates in plan
  identity and in every published artifact.
- Treat `TERMINAL_STATUSES` as the completion predicate, not a validity check. A row with
  `status="partial"` is a legitimate published result.
- Use `models.py` only for in-memory work. It is not a serialization format; the Arrow
  schema is the wire contract and is what the pipeline reads and writes.

## Public surface

| Symbol | Module |
| :--- | :--- |
| `DATASET_NAME`, `SCHEMA_VERSION`, `SUBMISSION_METADATA_SCHEMA` (28 columns) | `schemas.py` |
| `ADDRESS_STRUCT` (10 fields), `FORMER_NAME_STRUCT` (3), `LISTING_STRUCT` (2), `ANOMALY_STRUCT` (3), `FILING_STRUCT` (21), `SUBMISSION_FILE_STRUCT` (4) | `schemas.py` |
| `TERMINAL_STATUSES` | `schemas.py` |
| `Address`, `FormerName`, `Listing`, `FilingRecord`, `EntityProfile` (22 fields), `SubmissionsAggregate` | `models.py` |

No command surface.

## Tests

```text
tests/domain/submissions/test_schemas.py
tests/domain/submissions/test_models.py
```

## Deliberate gaps

- **`models.py` is deferred: no producer constructs these types.** All six dataclasses
  have no importer anywhere in `edgar_sec/`. The pipeline and engine work against the Arrow
  schema and against raw dicts — `worker.normalize_one_cik` returns a row dict, never a
  typed aggregate. They are retained as the domain vocabulary a future rendering/projection
  layer will read published Arrow rows into; that adapter does not exist, and
  `roadmap/refactor_v2/phase_1.md` §10 records the retirement as deferred rather than as
  dead code. Do not read them as live plumbing.
- **`test_models.py` pins that deferral.** Alongside the models' own invariants it asserts
  that `builder`, `filings`, `profile`, and `worker` construct none of them. When the
  projection adapter lands, that assertion is what should be replaced.
- **Schema coverage here is thin.** The 28-column schema, six struct types, and
  `TERMINAL_STATUSES` are pinned by a single test function. The transitive coverage is real
  — `tests/domain/filing_catalog/test_schemas.py:19` imports `SUBMISSION_METADATA_SCHEMA`
  and asserts the profile projection resolves — but it is not direct coverage.
- **No schema-validating code lives here.** There is no check that a fetched payload's keys
  match the struct fields, and no migration path for an older `SCHEMA_VERSION`. The merger
  validates row counts, coverage, and fingerprints; the engine's builder constructs the
  arrays. An unknown key goes to `extra_fields` by convention, not by a rule enforced here.
- **Nothing here validates identity.** `FILING_STRUCT.accession_number` is a plain
  `string`, not an `AccessionNumber`; Arrow cannot hold a dataclass. The `AccessionNumber`
  format check in `edgar_sec.domain.identity` runs where the value is built, not on read.
- **The dataset name is the contract, not the directory.** This package is `submissions/`
  (plural, naming the SEC endpoint) while the dataset it defines is `submission_metadata`
  (singular). They are deliberately different strings; do not unify them.