# Cross-Pipeline Integration & Migration Specification

This specification defines how Phase 01 (`metadata_sync`) and Phase 02 (`filing_catalog`) consume cohorts, as well as failure handling and data migration policies.

---

## 1. Metadata Sync Integration (Phase 01)

### 1.1 Decoupled Path Resolution & Symbol Removal
All cohort paths and symbols are removed from `edgar_sec/pipelines/metadata_sync/paths.py`:
- `COHORTS_DIR_NAME`, `COMPILED_ROSTER_MANIFEST_NAME`, `COMPILED_ROSTER_MANIFEST_KIND` removed.
- `MetadataPaths.cohorts_root`, `compiled_cohort_dir`, `compiled_cohort_file`, and `compiled_cohort_manifest` removed.
- Call sites in `metadata_sync` import downward from Layer 2 `edgar_sec.infra.storage.cohort`.

### 1.2 Pipeline Planning & CLI Wiring (`options.py` and `cli.py`)
1. **`PlanOptions` in `metadata_sync/options.py`**:
   - Stores strictly `cohort: str = ""` and `limit: int | None = None`.
   - Resolves cohort via `CohortCatalog(paths).resolve_cohort_identifier(self.cohort)` and loads canonical `ciks.parquet` into `Roster` via `cohort_record_to_roster(record, paths)`.
   - Removes legacy `--universe`, `--input`, and `--roster` fields.
2. **CLI Parser in `metadata_sync/cli.py`**:
   - `metadata plan`: requires `--cohort <id_or_name>` (with optional `--limit <n>`).
   - `metadata augment`: requires `--base-snapshot-id <id>` and `--cohort <id_or_name>` (delta cohort selector).
   - Deletes `sources refresh` and `sources compare` subcommands from `metadata_sync`.
   - Deletes shared `_add_cohort_source()` helper.
3. **Removal of Shims**:
   - Deletes `metadata_sync/manifest.py`, `universe.py`, and `cohort_adapter.py`.

---

## 2. Filing Catalog Integration (Phase 02)

Phase 02 utilizes cohorts for deterministic target filtering and policy seeding.

### 2.1 Deterministic Planning (`--cohort`) & Plan Identity Caching
1. **Extension Points & Real Seams**:
   - CLI parser: `edgar_sec/pipelines/filing_catalog/cli.py` adds `--cohort`.
   - Command handler: `edgar_sec/pipelines/filing_catalog/commands/plan.py:cmd_plan` passes `cohort=args.cohort` to `build_plan()`.
   - Planner entrypoint: `edgar_sec/pipelines/filing_catalog/planner.py:plan()`.
2. **Plan Identity & Request Fingerprint**:
   - The filing catalog hashes `request` via `plan_identity(request)` to cache/reuse plan bundles (`planner.py:183-201`).
   - When `--cohort` is passed, `plan()` resolves `CohortRecord` from `CohortCatalog` and injects:
     ```python
     request["cohort_id"] = record.cohort_id
     request["cohort_dataset_sha256"] = record.dataset_sha256
     ```
3. **Normalized SQL Semi-Join Binding**:
   - Target locator rows in filing catalog store CIK under column **`source_cik`** (`domain.filing_catalog.schemas.TARGET_SCHEMA`), not `cik_padded`.
   - The query binds using integer comparison to prevent padding mismatches:
     ```sql
     AND try_cast(source_cik AS BIGINT) IN (
         SELECT try_cast(cik_padded AS BIGINT) FROM read_parquet(?)
     )
     ```

### 2.2 Policy Selection (`--seed-cohort`) & `SeedFiler` Provenance
1. **CLI & Command Seam**:
   - `cli.py` and `commands/plan.py` add `--seed-cohort`.
   - `planner.py:plan_policy()` receives `seed_cohort`.
2. **`SeedFiler` Conversion**:
   - When `--seed-cohort <id_or_name>` is provided, read `ciks.parquet` and convert each row into:
     ```python
     SeedFiler(
         cik=cik_padded,
         group="cohort",
         tag=cohort_record.name or cohort_record.cohort_id,
         note=f"From cohort {cohort_record.cohort_id}",
     )
     ```
3. **Precedence & Mutex**:
   - `--seed-cohort` replaces policy-configured seed CSV files.
   - Passing both `--seed-cohort` and `--seed-csv` raises `ConflictError("Cannot pass both --seed-cohort and --seed-csv")`.

### 2.3 Company Family Index Consumer Contract
1. **Prerequisite Publication**:
   - `filing_catalog.planner` does not compile or publish the family index dynamically.
   - Publication is an explicit prerequisite managed by `edgar-sec cohort family-index publish`.
2. **Artifact Resolution**:
   - Resolves the active family index record via Layer 2 `CohortCatalog.get_active_family_index(universe_cohort_id)`.
   - Resolves the Parquet file path via Layer 2 `CohortPaths.family_index_file(family_index_id)`.
3. **Fail-Closed on Missing or Stale**:
   - If the active family index is missing, stale (universe changed), or corrupt (`file_sha256` mismatch), `filing_catalog.planner` strictly fails closed with `FamilyIndexNotFoundError`.

### 2.4 Strict Failure Contracts & Edge Case Guarantees
1. **Fail-Closed on Missing or Corrupt Cohorts**:
   - If `--cohort` or `--seed-cohort` cannot be resolved or its Parquet file is unreadable/corrupt, planning **fails immediately with a nonzero exit code**.
2. **Empty Cohort Guarantee**:
   - If a cohort is valid but contains 0 CIKs (empty cohort), planning must produce **exactly 0 targets**.

---

## 3. Legacy Cohort Migration & Compatibility Policy

In strict accordance with `AGENTS.md` ("Zero Backward-Compatibility Shims"):

1. **No Runtime Compatibility Code**:
   - Library modules will **not** attempt runtime fallback checks against `.artifacts/metadata/cohorts/` or disk `active_pointer.json`.
   - All runtime operations query `.artifacts/cohorts/cohorts.sqlite`.
2. **Rebuild / Discard Default**:
   - Existing `.artifacts/metadata/cohorts/` directories are treated as deprecated and discarded.
   - Official sources are populated cleanly via `edgar-sec cohort sources refresh`.
3. **No Migration Utility**:
   - No offline scratch migration script is provided. Stale or unmanaged legacy scratch artifacts are discarded or re-ingested via standard CLI commands (`edgar-sec cohort import`).
