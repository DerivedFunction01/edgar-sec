# Cross-Pipeline Integration & Migration Specification

This specification defines how Phase 01 (`metadata_sync`) and Phase 02 (`filing_catalog`) consume cohorts, as well as failure handling and data migration policies.

---

## 1. Metadata Sync Integration (Phase 01)

### 1.1 Decoupled Path Resolution & Symbol Removal
All cohort paths and symbols are removed from `edgar_sec/pipelines/metadata_sync/paths.py`:
- `COHORTS_DIR_NAME`, `COMPILED_ROSTER_MANIFEST_NAME`, `COMPILED_ROSTER_MANIFEST_KIND` removed.
- `MetadataPaths.cohorts_root`, `compiled_cohort_dir`, `compiled_cohort_file`, and `compiled_cohort_manifest` removed.
- Call sites in `metadata_sync` import downward from `edgar_sec.infra.storage.cohort`.

### 1.2 Pipeline Planning & CLI Wiring (`options.py` and `cli.py`)
1. **`PlanOptions` in `metadata_sync/options.py`**:
   - Add field `cohort: str = ""` to `PlanOptions`.
   - Update `roster(self) -> Roster`:
     If `self.cohort` is provided, resolve the cohort from `CohortCatalog` and convert to `Roster` via adapter `cohort_record_to_roster(record, paths)`.
   - Update mutual exclusion: `--cohort`, `--universe`, `--input`, and `--roster` are strictly mutually exclusive.
2. **CLI Parser in `metadata_sync/cli.py`**:
   - Expose `--cohort <name_or_id>` on `edgar-sec metadata plan`.
3. **Interactive Menu (`augment_flow.py`)**:
   - Replace `ask_cohort_source` with paginated `CohortCatalog` picker, eliminating the combinatorial explosion of seed CSVs and universe snapshots.
4. **Augmentation Flow (`augmentation.py`)**:
   - Replaces manual row-diffing queries with `operations.execute_delta_roster(cohort_dataset, base_cik_map, output_dataset)`.
5. **Universe & Official Sources (`universe.py`, `source_registry.py`)**:
   - `source_registry.py` delegates snapshot acquisition to `edgar_sec.infra.storage.cohort.sources` (Layer 2).
   - Universe snapshot resolution uses `sources.resolve_active_source("cik_lookup", catalog)` instead of directory walking.

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
   - This ensures different cohorts produce distinct plan IDs, preventing erroneous reuse of cached plans.
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
   - The resolved `SeedFiler` list is included in the policy plan request fingerprint.

### 2.3 Strict Failure Contracts & Edge Case Guarantees
1. **Fail-Closed on Missing or Corrupt Cohorts**:
   - If `--cohort` or `--seed-cohort` cannot be resolved or its Parquet file is unreadable/corrupt, planning **fails immediately with a nonzero exit code**.
   - Under no circumstances does the planner log a warning and proceed without the filter.
2. **Empty Cohort Guarantee**:
   - If a cohort is valid but contains 0 CIKs (empty cohort), planning must produce **exactly 0 targets**.
   - It must never omit the semi-join or silently plan against the entire filing catalog.

---

## 3. Legacy Cohort Migration & Compatibility Policy

In strict accordance with `AGENTS.md` ("Zero Backward-Compatibility Shims"):

1. **No Runtime Compatibility Code**:
   - Library modules will **not** attempt runtime fallback checks against `.artifacts/metadata/cohorts/` or disk `active_pointer.json`.
   - All runtime operations query `.artifacts/cohorts/cohorts.sqlite`.
2. **Rebuild / Discard Default**:
   - Existing `.artifacts/metadata/cohorts/` directories are treated as deprecated and discarded.
   - Official sources are populated cleanly via `edgar-sec cohort refresh-sources`.
3. **Offline Scratch Migration Script**:
   - For local development machines with custom cohorts, an offline script `scratch/migrate_legacy_cohorts.py` is provided to read legacy `.artifacts/metadata/cohorts/` and import them into `CohortCatalog`.
   - This script is not part of library code and is not imported by pipelines.
