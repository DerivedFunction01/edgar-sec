# `edgar_sec/infra/storage/cohort`

This package owns shared CIK datasets, their catalog, source snapshots, and
set/query operations. Dataset paths persisted in SQLite are relative to the
configured `cohorts_root`.

## Module Map

| Module | Responsibility |
| :--- | :--- |
| `paths.py` | `CohortPaths`, configured root resolution, bounded relative paths, and staging publication. |
| `models.py` | Immutable `CohortRecord` and its manifest representation. |
| `catalog.py` | WAL SQLite schema, cohort metadata, tags, source pointers, manifests, and lifecycle guards. |
| `sources.py` | Official SEC reference source acquisition and active snapshot resolution. |
| `ingestion.py` | Streaming CSV/TSV/TXT/Parquet intake and canonical cohort publication. |
| `operations.py` | Set algebra, safe expression AST compilation, roster deltas, and deterministic sampling. |
| `query.py` | Stable paginated cohort membership and search. |
| `workspace.py` | Session variables, immutable expression nodes, previews, and saved results. |
| `__init__.py` | Package docstring only; no re-exports. |

## Contracts

- Cohort directories and persisted dataset paths cannot resolve outside
  `cohorts_root`.
- SQLite connections use WAL mode, foreign keys, and normal synchronous mode;
  fresh catalog files use 8192-byte pages.
- Generic cohort identity is `c-` plus the first 16 lowercase hexadecimal
  characters of the CIK-roster SHA-256. Official-source identity instead uses
  the first 16 characters of its validated full `source_snapshot_id` SHA-256;
  each record still stores the CIK-roster digest independently. Published
  dataset bytes are verified against their recorded digest.
- A CIK is the membership key; datasets contain each CIK once. Intake chooses
  the first non-empty trimmed name in input order. Union and intersection prefer
  the left operand's non-empty name, then the right; callers put the authoritative
  source first. A name-less row remains blank unless the other operand supplies a
  name.
- A different dataset payload for an existing cohort identity is rejected.
  Official source snapshots with the same CIK set but changed names remain
  separate immutable records, and active source pointers target their cohort IDs.
- Staging directories are siblings of final cohort directories, allowing an
  atomic directory rename on the same filesystem. Failed catalog registration
  removes the unpublished catalog entry's final directory.
- Manifests use canonical JSON. Deletion refuses pinned or active-source cohorts;
  workspace alias references require explicit force, which removes those aliases.

## Public Surface

- `CohortPaths` and `resolve_cohort_paths()` in [`paths.py`](paths.py).
- `CohortRecord` in [`models.py`](models.py).
- `CohortCatalog`, `write_manifest()`, and lifecycle errors in
  [`catalog.py`](catalog.py).
- `refresh_official_source()` and `resolve_active_source()` in
  [`sources.py`](sources.py).
- `ingest_file_to_cohort()` and `publish_derived_cohort()` in
  [`ingestion.py`](ingestion.py).
- `execute_set_operation()`, `execute_delta_roster()`, `sample_cohort()`, and
  `compile_ast_to_sql()` in [`operations.py`](operations.py).
- `query_cohort_members()` and `find_across_cohorts()` in [`query.py`](query.py).
- `CohortWorkspace` in [`workspace.py`](workspace.py).

**Command surface:** none.

## Mirrored Tests

`tests/infra/storage/cohort/`.

## Deliberate Gaps

- Family-index generation is owned by the metadata pipeline; family-grouped
  sampling requires the caller to supply its verified assignment dataset.
- Stale staging cleanup is explicit through `cleanup_stale_staging()`; this
  package does not schedule process-start cleanup or reconcile orphan final
  directories left by abrupt process termination between rename and commit.
