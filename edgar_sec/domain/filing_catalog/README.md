# `edgar_sec/domain/filing_catalog/` — Catalog schemas, version constants, and filter vocabulary

This package owns the catalog schemas and planning filter vocabulary.

## Purpose

Declares the published catalog schemas, schema-version identifiers, locator-column
vocabulary, and document-suffix filters shared by planning and selection. SQL and
planning implementations belong to the infrastructure and pipeline layers.

## Layout

| Module | Responsibility |
| :--- | :--- |
| `schemas.py` | Catalog/profile schemas, version identifiers, locator-column vocabulary, planning scopes |
| `filters.py` | `DEFAULT_DOCUMENT_SUFFIXES`, `normalize_suffixes()` |

## Contracts

- `PROFILE_SCHEMA` borrows shared field definitions from
  `SUBMISSION_METADATA_SCHEMA` and adds catalog-specific fields. A submission
  schema change is therefore reflected when the profile schema is constructed.
- The target shape and column order are declared together. A form is selected by naming it exactly; an
  amendment variant such as `10-K/A` is a distinct form value, not a derived
  flag.
- Locator columns and selection features are declared once so writers and
  consumers share the same ordering. `LOCATOR_POLICY_COLUMNS` is derived from its two
  parts rather than restated, and `LOCATOR_FEATURE_COLUMNS` /
  `OCCURRENCE_FEATURE_COLUMNS` are what the selection engine projects from.
- Schema and profile versions are tracked independently, so a profile change does
  not force a target-schema bump: `SCHEMA_VERSION`, `TARGET_SCHEMA_VERSION`,
  `PROFILE_SCHEMA_VERSION`.
- Target plan version 1.3 declares target-part row counts, sizes, and SHA-256
  digests for consumers that require payload integrity pins.
- Path provenance is a closed vocabulary: `PATH_SOURCE_PRIMARY` and
  `PATH_SOURCE_BUNDLE`.
- Suffix inputs are normalized and validated by `normalize_suffixes()`; invalid
  values are rejected rather than interpolated into a query.
- `normalize_suffixes()` preserves order and is stable under repetition because
  suffix ordering participates in plan identity.

**Obligations on callers.**

- Pass user-supplied suffixes through `normalize_suffixes()` before they reach a
  plan or SQL predicate; invalid values are errors.
- Bump the right version constant when a schema changes; do not silently redefine a column
  type in place.
- Name a plan scope (`SCOPE_DETERMINISTIC`, `SCOPE_POLICY`) when reading a bundle; the two
  scopes publish deliberately different occurrence schemas.

## Public surface

| Symbol | Module |
| :--- | :--- |
| `DATASET_NAME` (`"filing_catalog"`), `SCHEMA_VERSION`, `TARGET_SCHEMA_VERSION`, `PROFILE_SCHEMA_VERSION`, `TARGET_PLAN_SCHEMA_VERSION`, `READABLE_TARGET_PLAN_SCHEMA_VERSIONS` | `schemas.py` |
| `PATH_SOURCE_PRIMARY`, `PATH_SOURCE_BUNDLE` | `schemas.py` |
| `PROFILE_COLUMNS`, `PROFILE_SCHEMA`, `TARGET_COLUMNS`, `TARGET_SCHEMA` | `schemas.py` |
| `LOCATOR_BASE_COLUMNS`, `LOCATOR_POLICY_FEATURES`, `LOCATOR_POLICY_COLUMNS` | `schemas.py` |
| `LOCATOR_FEATURE_COLUMNS`, `OCCURRENCE_FEATURE_COLUMNS` | `schemas.py` |
| `SCOPE_DETERMINISTIC`, `SCOPE_POLICY` | `schemas.py` |
| `SUBMISSION_METADATA_SCHEMA` (re-export of the Phase 1 schema, borrowed by `PROFILE_SCHEMA`) | `schemas.py` |
| `DEFAULT_DOCUMENT_SUFFIXES`, `normalize_suffixes(values)` | `filters.py` |

No command surface.

## Tests

Mirrored coverage lives under `tests/domain/filing_catalog/`.

## Deliberate gaps

- SQL construction and execution live with whoever owns the statement: the
  catalog materialization queries in `pipelines/filing_catalog`, the date and
  suffix predicate compilers in `engine/selection`, and the DuckDB dialect
  primitives in `infra/storage`. This package intentionally provides their
  shared schema and filter vocabulary only.
