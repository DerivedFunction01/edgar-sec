# `edgar_sec/domain/filing_catalog/` — Catalog schemas, version constants, and filter vocabulary

What a published filing-catalog row looks like, and which documents a run is
allowed to select. Two modules, both pure: an Arrow schema set and a validating
normalizer.

## Purpose

`edgar_sec/domain/filing_catalog/` declares the catalog's on-disk shape
(`TARGET_SCHEMA`, `PROFILE_SCHEMA`, the locator column tuples, the three version
constants) and the filter vocabulary that two different layers must agree on
(amendment policies, document suffixes, and the suffix normalizer). It is not the
SQL that reads or writes the catalog (that is
`infra/storage/duckdb_catalog.py`) and not the planning that consumes the
vocabulary (that is `pipelines/filing_catalog/` and `engine/selection/`).

## Layout

| Module | Responsibility |
| :--- | :--- |
| `schemas.py` | `TARGET_SCHEMA`, `PROFILE_SCHEMA`, the three version constants, `PROFILE_COLUMNS`, `TARGET_COLUMNS`, and the three locator column tuples |
| `filters.py` | `AMENDMENT_POLICIES`, `DEFAULT_AMENDMENT`, `DEFAULT_DOCUMENT_SUFFIXES`, and the validating `normalize_suffixes()` |

## Contracts

**Guarantees this package makes.**

- `PROFILE_SCHEMA` borrows its field definitions by reference, not by restatement.
  `schemas.py:78-81` builds it from
  `[SUBMISSION_METADATA_SCHEMA.field(name) for name in PROFILE_COLUMNS[:-1]]`, so
  a Phase 1 schema change raises at import time here rather than surfacing later
  as silent column drift during materialization. `PROFILE_COLUMNS` is 23 names
  long — the 22 borrowed Phase 1 columns plus the catalog-owned
  `profile_schema_version` — and the resulting `pa.schema` has exactly 23 fields.
- The target shape is fixed and declared. `TARGET_COLUMNS` and `TARGET_SCHEMA`
  both have 16 fields, in the same order: `occurrence_id`,
  `document_locator_key`, `source_cik`, `accession`, `form`, `is_amendment`,
  `filing_date`, `report_date`, `primary_document`, `document_path`,
  `archive_url`, `document_path_source`, `reported_size`, `is_xbrl`,
  `is_inline_xbrl`, `is_xbrl_numeric`.
- Column ordering is shared, not copied. `LOCATOR_BASE_COLUMNS` (8 identity
  columns), `LOCATOR_POLICY_FEATURES` (10 stratification dimensions), and
  `LOCATOR_POLICY_COLUMNS` (18 = 8 identity + 10 features) are declared here "so
  the writer and any consumer share one ordering rather than each keeping a copy
  of the list" (`schemas.py:117-120`).
- Three independent version constants exist, so a profile change does not force
  a target-schema bump: `SCHEMA_VERSION`, `TARGET_SCHEMA_VERSION`, and
  `PROFILE_SCHEMA_VERSION` (`schemas.py:22-25`).
- Path provenance is a closed vocabulary of two values:
  `PATH_SOURCE_PRIMARY = "primary_document"` and
  `PATH_SOURCE_BUNDLE = "submission_bundle"`.
- Amendment policy is a closed set of three: `AMENDMENT_POLICIES` is
  `("both", "original", "amendments")` with `DEFAULT_AMENDMENT = "both"`. The
  module docstring is explicit about why this is a *shared* closed set: two
  layers need it, and restating it in each would create two definitions of what
  `original` means.
- Suffixes are validated, not sanitised. `normalize_suffixes()` lower-cases,
  strips leading dots, drops empties, de-duplicates, and rejects anything
  outside `^[a-z0-9][a-z0-9.]*$` with a `ValueError` (`filters.py:33,54-58`).
  The module docstring records the v1 hazard this replaces: v1 interpolated the
  column name and each suffix straight into a SQL string literal, so a suffix
  containing a quote could terminate the literal. v2 fails loudly at the call
  site instead.
- `normalize_suffixes()` preserves order and is stable under repetition. Order
  participates in a plan's identity hash, and de-duplication keeps that hash
  stable when a caller repeats a suffix (`filters.py:42-46`).
- `normalize_suffixes()` raises `ValueError` for a non-string element rather than
  stringifying it (`filters.py:49-50`).

**Obligations callers place on this package.**

- Pass user-supplied suffixes through `normalize_suffixes()` before they reach a
  plan or a SQL predicate. A non-`str` element and an out-of-alphabet
  character are both hard errors by design.
- Keep the amendment-policy consumers in step. Four modules import this
  vocabulary: `pipelines/filing_catalog/planner.py:26`,
  `pipelines/filing_catalog/expansion.py:31` (`normalize_suffixes` only),
  `engine/selection/policy.py:36`, and `engine/selection/source.py:34`, with
  `infra/storage/duckdb_catalog.py:26` reading `AMENDMENT_POLICIES` for its
  SQL predicate.
- Bump the right version constant when a schema changes; do not silently
  redefine a column type in place.
- Import `SEC_ARCHIVE_BASE` from `edgar_sec.domain.sec_urls` in new code, not
  from this package (see deliberate gaps).

## Public surface

- `DATASET_NAME` — `"filing_catalog"`; `schemas.py:20`.
- `SCHEMA_VERSION`, `TARGET_SCHEMA_VERSION`, `PROFILE_SCHEMA_VERSION` — all
  `"1.1.0"`, `"1.1.0"`, and `"1.0.0"` respectively; `schemas.py:23-25`.
- `PATH_SOURCE_PRIMARY`, `PATH_SOURCE_BUNDLE` — `schemas.py:28-29`.
- `PROFILE_COLUMNS` (23 names), `TARGET_COLUMNS` (16 names) — `schemas.py:33`,
  `schemas.py:59`.
- `PROFILE_SCHEMA`, `TARGET_SCHEMA` — `pa.schema` objects; `schemas.py:78`,
  `schemas.py:83`.
- `LOCATOR_BASE_COLUMNS` (8), `LOCATOR_POLICY_FEATURES` (10),
  `LOCATOR_POLICY_COLUMNS` (18) — `schemas.py:106`, `:121`, `:134`.
- `AMENDMENT_POLICIES`, `DEFAULT_AMENDMENT`, `DEFAULT_DOCUMENT_SUFFIXES`,
  `normalize_suffixes(values)` — `filters.py:35-61`. Note
  `DEFAULT_DOCUMENT_SUFFIXES` is the empty tuple: there is no default suffix
  filter, and a caller that wants one must state it.

## Tests

```text
tests/domain/filing_catalog/test_schemas.py    12 test functions, 111 lines
tests/domain/filing_catalog/test_filters.py     6 test functions,  48 lines
```

`test_schemas.py` imports `SUBMISSION_METADATA_SCHEMA` directly, so the
by-reference projection is asserted against the real Phase 1 schema rather than
a copy of it.

## Deliberate gaps

- **No SQL builders here, by decision.** `filters.py`'s docstring records that
  Stage A kept the vocabulary in `pipelines/filing_catalog/filters.py` alongside
  two SQL builders; Stage B could not reuse it, because Layer 3 (`engine`) may
  not import Layer 4 (`pipelines`). Rather than restate `AMENDMENT_POLICIES` in
  the selection policy, the vocabulary moved down here and the SQL builders moved
  down with it to `infra.storage.duckdb_catalog`. The alternative — a second
  definition of the amendment vocabulary — is the outcome this layout prevents.
- **`SEC_ARCHIVE_BASE` is re-exported in this package's `__all__` and is
  actually consumed that way.** `infra/storage/duckdb_catalog.py:32` imports
  `SEC_ARCHIVE_BASE` from `domain.filing_catalog.schemas`, not from
  `domain.sec_urls`, even though `schemas.py:17` imports it from there. This is
  not an `__init__.py` barrel and does not breach `AGENTS.md` §1.2, but it is a
  cross-package re-export of another module's symbol. The owning module is
  `edgar_sec/domain/sec_urls.py`; `roadmap/refactor_v2/phase_2.md:753-754`
  records the duplicate's retirement in the opposite direction.
- **`company_family` is deliberately absent from `PROFILE_COLUMNS`.** The module
  docstring is explicit: the v1 README claimed the column existed, but no v1 code
  path ever wrote it, and clustering is a Stage B selection feature
  (`roadmap/refactor_v2/phase_2.md` decision D2). Do not add it here to satisfy
  the v1 documentation.
- **The Stage B widening is declared but not produced.** `LOCATOR_POLICY_FEATURES`
  and `LOCATOR_POLICY_COLUMNS` name the ten stratification dimensions Stage B
  will emit (`form_family`, `era`, `suffix`, `xbrl_state`, `size_band`,
  `owner_org_presence`, `foreign_status`, `lifecycle_class`, `stub_suspect`,
  `company_name`), while `schemas.py:104-105` describes Stage A as emitting only
  the narrow `LOCATOR_BASE_COLUMNS` projection. No module in this package
  materialises the policy file; the writer is `engine/selection/`, which imports
  `TARGET_COLUMNS` at `features.py:43` and `LOCATOR_POLICY_COLUMNS` at
  `pipelines/filing_catalog/planner.py:32`.
- **No validation, discovery, planning, or publication logic lives here.** The
  planner validates a plan; `publication.plan_bundle_complete` and the plan
  identity hash live in `pipelines/filing_catalog/`. The contract test that
  pins the plan bundle, `document_locator_key` uniqueness, non-null HTTPS
  `archive_url`, occurrence keying, and reserve disjointness is
  `tests/pipelines/filing_catalog/test_phase25_contract.py`.
