# `edgar_sec/domain/filing_catalog/` — Catalog schemas, version constants, and filter vocabulary

This package owns the catalog schemas and planning filter vocabulary.

## Purpose

Declares the published catalog schemas, schema-version identifiers, locator-column
vocabulary, and document-suffix filters shared by planning and selection. SQL and
planning implementations belong to the infrastructure and pipeline layers.

## Contracts

- **Arrow schema stability**: `PROFILE_SCHEMA` borrows shared fields from `SUBMISSION_METADATA_SCHEMA` and adds catalog-specific fields.
- **Target shape declaration**: Column order is declared together; amendments like `10-K/A` are distinct form values.
- **Deterministic keys**: Locator columns and selection features are declared once; `LOCATOR_POLICY_COLUMNS` is derived rather than restated.
- **Schema versioning**: Schema and profile versions are tracked independently (`SCHEMA_VERSION`, `TARGET_SCHEMA_VERSION`, `PROFILE_SCHEMA_VERSION`).
- **Payload integrity**: Target plan version 1.3 declares target-part row counts, sizes, and SHA-256 digests.
- **Path provenance**: Path provenance is a closed vocabulary (`PATH_SOURCE_PRIMARY`, `PATH_SOURCE_BUNDLE`).
- **Suffix validation**: Suffix inputs are normalized and validated by `normalize_suffixes()`; invalid values are rejected.

**Obligations on callers.**

- Pass user-supplied suffixes through `normalize_suffixes()` before they reach a
  plan or SQL predicate; invalid values are errors.
- Bump the right version constant when a schema changes; do not silently redefine a column
  type in place.
- Name a plan scope (`SCOPE_DETERMINISTIC`, `SCOPE_POLICY`) when reading a bundle; the two
  scopes publish deliberately different occurrence schemas.

## Deliberate gaps

- **No SQL construction or execution**: SQL queries belong to catalog materialization, selection, and storage layers.
