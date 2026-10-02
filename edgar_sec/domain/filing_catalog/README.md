# `edgar_sec/domain/filing_catalog/` — Catalog schemas, version constants, and filter vocabulary

What a published filing-catalog row looks like, and which documents a run may select.
Two modules, both pure: an Arrow schema set and a validating normalizer.

## Purpose

Declares the catalog's on-disk shape (`TARGET_SCHEMA`, `PROFILE_SCHEMA`, the locator
column tuples, the three version constants) and the filter vocabulary two different
layers must agree on (amendment policies, document suffixes, and the suffix normalizer).
Not the SQL that reads or writes the catalog (`infra/storage/duckdb_catalog.py`), and
not the planning that consumes the vocabulary (`pipelines/filing_catalog/`,
`engine/selection/`).

## Layout

| Module | Responsibility |
| :--- | :--- |
| `schemas.py` | `TARGET_SCHEMA`, `PROFILE_SCHEMA`, the three version constants, `PROFILE_COLUMNS`, `TARGET_COLUMNS`, the three locator column tuples, and the two planning scopes |
| `filters.py` | `AMENDMENT_POLICIES`, `DEFAULT_AMENDMENT`, `DEFAULT_DOCUMENT_SUFFIXES`, `normalize_suffixes()` |

## Contracts

- `PROFILE_SCHEMA` borrows its field definitions by reference, not by restatement:
  it is built from `[SUBMISSION_METADATA_SCHEMA.field(name) for name in PROFILE_COLUMNS[:-1]]`
  plus the catalog-owned `profile_schema_version`. A Phase 1 schema change therefore
  raises here at import time instead of surfacing later as silent column drift.
  23 columns in, 23 fields out.
- The target shape is fixed and declared: `TARGET_COLUMNS` and `TARGET_SCHEMA` both have
  16 fields in the same order.
- Column ordering is shared, not copied. `LOCATOR_BASE_COLUMNS` (8 identity columns),
  `LOCATOR_POLICY_FEATURES` (10 stratification dimensions), and
  `LOCATOR_POLICY_COLUMNS` (18 = 8 + 10) are declared once here so the writer and any
  consumer share one ordering.
- Three independent version constants exist, so a profile change does not force a
  target-schema bump: `SCHEMA_VERSION`, `TARGET_SCHEMA_VERSION`, `PROFILE_SCHEMA_VERSION`.
- Path provenance is a closed vocabulary of two values, `PATH_SOURCE_PRIMARY` and
  `PATH_SOURCE_BUNDLE`.
- Amendment policy is a closed set of three: `AMENDMENT_POLICIES` is
  `("both", "original", "amendments")`, `DEFAULT_AMENDMENT = "both"`. The module
  docstring is explicit that this is a *shared* set: two layers need it, and restating
  it in each would create two definitions of what `original` means.
- Suffixes are validated, not sanitised. `normalize_suffixes()` lower-cases, strips
  leading dots, drops empties, de-duplicates, rejects a non-`str` element, and rejects
  anything outside `^[a-z0-9][a-z0-9.]*$` with `ValueError`. The module docstring records
  the v1 hazard: v1 interpolated the column name and each suffix into a SQL string
  literal, so a quote could terminate it.
- `normalize_suffixes()` preserves order and is stable under repetition. Order participates
  in a plan's identity hash; de-duplication keeps that hash stable under a repeated suffix.

**Obligations on callers.**

- Pass user-supplied suffixes through `normalize_suffixes()` before they reach a plan or
  a SQL predicate. A non-`str` element and an out-of-alphabet character are both hard errors.
- Bump the right version constant when a schema changes; do not silently redefine a column
  type in place.
- Name a plan scope (`SCOPE_DETERMINISTIC`, `SCOPE_POLICY`) when reading a bundle; the two
  scopes publish deliberately different occurrence schemas.

## Public surface

| Symbol | Module |
| :--- | :--- |
| `DATASET_NAME` (`"filing_catalog"`), `SCHEMA_VERSION`, `TARGET_SCHEMA_VERSION`, `PROFILE_SCHEMA_VERSION` | `schemas.py` |
| `PATH_SOURCE_PRIMARY`, `PATH_SOURCE_BUNDLE` | `schemas.py` |
| `PROFILE_COLUMNS` (23), `PROFILE_SCHEMA`, `TARGET_COLUMNS` (16), `TARGET_SCHEMA` | `schemas.py` |
| `LOCATOR_BASE_COLUMNS` (8), `LOCATOR_POLICY_FEATURES` (10), `LOCATOR_POLICY_COLUMNS` (18) | `schemas.py` |
| `SCOPE_DETERMINISTIC`, `SCOPE_POLICY` | `schemas.py` |
| `SUBMISSION_METADATA_SCHEMA` (re-export of the Phase 1 schema, borrowed by `PROFILE_SCHEMA`) | `schemas.py` |
| `AMENDMENT_POLICIES`, `DEFAULT_AMENDMENT`, `DEFAULT_DOCUMENT_SUFFIXES` (empty tuple), `normalize_suffixes(values)` | `filters.py` |

No command surface.

## Tests

```text
tests/domain/filing_catalog/test_schemas.py
tests/domain/filing_catalog/test_filters.py
```

`test_schemas.py` imports `SUBMISSION_METADATA_SCHEMA` directly, so the by-reference
projection is asserted against the real Phase 1 schema rather than a copy of it.

## Deliberate gaps

- **No SQL builders here, by decision.** `filters.py`'s docstring records that Stage A
  kept this vocabulary in `pipelines/filing_catalog/filters.py` alongside two SQL builders;
  Stage B could not reuse it, because Layer 3 may not import Layer 4. Rather than restate
  `AMENDMENT_POLICIES` in the selection policy, the vocabulary moved down here and the SQL
  builders moved down to `infra.storage.duckdb_catalog`. The alternative — a second
  definition of the amendment vocabulary — is the outcome this layout prevents.
- **`company_family` is deliberately absent from `PROFILE_COLUMNS`.** The module docstring
  is explicit: the v1 README claimed the column existed, but no v1 code path ever wrote it,
  and clustering is a Stage B selection feature (`roadmap/refactor_v2/phase_2.md` decision D2).
- **The Stage B widening is declared but not produced.** `LOCATOR_POLICY_FEATURES` and
  `LOCATOR_POLICY_COLUMNS` name the ten stratification dimensions Stage B will emit, while
  the module describes Stage A as emitting only the narrow `LOCATOR_BASE_COLUMNS` projection.
  No module here materialises the policy file; the writer is `engine/selection/`
  (`features.py:43` imports `TARGET_COLUMNS`) and `pipelines/filing_catalog/planner.py:28`
  imports `LOCATOR_POLICY_COLUMNS`.
- **No validation, discovery, planning, or publication logic lives here.** The planner
  validates a plan; the plan identity hash and `publication.plan_bundle_complete` live in
  `pipelines/filing_catalog/`. The contract test that pins the plan bundle,
  `document_locator_key` uniqueness, non-null HTTPS `archive_url`, occurrence keying, and
  reserve disjointness is `tests/pipelines/filing_catalog/test_phase25_contract.py`.