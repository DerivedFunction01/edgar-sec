# Phase 02: Filing Catalog

This phase derives immutable, no-network filing catalogs from the finalized
Phase 01 `submission_metadata` Parquet artifact. `materialize` expands nested
filing observations into form-partitioned targets and `plan` applies
deterministic form and amendment filters. Phase 01 chunks are never read.
This phase performs no network access and does not fetch filing documents.

## Interactive runner

Selecting `Phase 02: Filing Catalog` from `python run.py` opens a phase-specific
menu; direct flags also pass through to the canonical CLI:

```text
python run.py filing-catalog          # interactive menu
python run.py filing-catalog materialize --source-manifest <manifest>
python run.py filing-catalog plan --catalog <catalog-directory>
```

The interactive menu offers:

1. Materialize catalog — pick a finalized Phase 01 artifact or manifest and an
   output root; produces a catalog directory through bounded DuckDB staging.
2. Plan filing targets — pick a catalog, optional form filters (defaulting to
    any configured `target_forms`), an amendment policy (`both`/`original`/`amendments`),
    and an optional limit; writes an immutable target-plan directory.
3. Show status — lists discovered catalogs and target plans from their manifests
   and `plan.json` files without scanning Parquet rows or re-fetching source data.
0. Exit

Prompts show workspace-derived defaults. In the standard local layout, blank
materialization input selects the finalized Phase 01
`manifests/metadata/submission_metadata/final/submission_metadata.parquet` artifact when present,
and blank output inputs use transient staging and runs under
`transient/filing_extraction/` under `ARTIFACTS_ROOT`. If exactly one published
manifest group is available, blank planning input selects it automatically. Materialization and
planning show a tqdm stage bar (source validation, company profiles, per-form
targets, occurrence sources, manifest publication) so long DuckDB and hashing
steps report progress instead of appearing to hang. The canonical CLI accepts an
optional `--progress` flag on `materialize` and `plan` for the same events.

Materialization uses a configurable source-row batch size (default 1,000) and
disk-backed DuckDB staging tables. Execution threads, memory budget, and spill
directory are machine-derived (`psutil` with an `os` fallback) and are never
persisted. Container or shared-host overrides are available through the
generated environment names `RUNTIME_THREADS`, `RUNTIME_MEMORY_LIMIT`,
`RUNTIME_MEMORY_FRACTION`, and `RUNTIME_TEMP_DIRECTORY`.

## Phase settings vs machine-local settings

Phase behavior is declared in this phase's `settings.py`
(`filing_extraction.source_batch_size`, `filing_extraction.target_forms`,
`filing_extraction.amendment`) and registered through the
`phases/settings.py` barrel; persistable dataset-relevant settings are written
to `.artifacts/filing_extraction/config.json`. Shared runtime execution settings
live in the shared registry
(`defs/runtime/settings/runtime.py`) and are machine-local: they affect how a
machine executes work but are never part of dataset identity, so they default
to machine detection and are not written to config or plans.

Resolution precedence for `source_batch_size`: explicit `--source-batch-size`
flag → direct environment/`.env` (`FILING_EXTRACTION_SOURCE_BATCH_SIZE`) →
persisted Phase 02 config → default. Resolution precedence for `target_forms`
and `amendment`: explicit `--form`/`--amendment` flags → direct environment/`.env`
(`FILING_EXTRACTION_TARGET_FORMS`, `FILING_EXTRACTION_AMENDMENT`) → persisted
Phase 02 config → default (`target_forms` empty means all forms, `amendment`
defaults to `both`). Runtime execution settings resolve as CLI flag →
environment → machine-derived value.

## Canonical command surface

```bash
.venv/bin/python -m phases.02_filing_extraction.cli materialize \
  --source-artifact .artifacts/manifests/metadata/submission_metadata/final/submission_metadata.parquet
.venv/bin/python -m phases.02_filing_extraction.cli materialize \
  --source-manifest .artifacts/manifests/metadata/submission_metadata/final/<artifact-id>.json
.venv/bin/python -m phases.02_filing_extraction.cli plan --catalog <catalog-id-or-final-manifest-directory>
.venv/bin/python -m phases.02_filing_extraction.cli expand \
  --parent-plan <fixture-plan-directory> --target-units 10000 \
  --selection-policy <selection-policy.json>
.venv/bin/python -m phases.02_filing_extraction.cli status
```

`materialize` accepts machine-tuning overrides: `--source-batch-size`,
`--threads`, `--memory-limit`, `--temp-directory`, and `--progress`. Explicit
flags override the persisted Phase 02 configuration at
`.artifacts/filing_extraction/config.json` (`--config` relocates it), which
holds `source_batch_size`, `target_forms`, and `amendment`; when neither is
present the conservative defaults (1,000 source rows per batch, all forms, and
`both` amendments) apply. DuckDB threads, memory budget,
and spill directory default to machine-derived values (`psutil` with an `os`
fallback) and may be overridden per environment through
`DUCKDB_THREADS`, `DUCKDB_MEMORY_LIMIT`,
`DUCKDB_MEMORY_FRACTION`, and `DUCKDB_TEMP_DIRECTORY` without
touching project configuration. All of these resolve through the shared
settings registry (`defs/runtime/settings/`), not ad-hoc environment reads.

Final manifests share a materialization/catalog ID and record the source
artifact identity and schema version; discovery groups those manifests rather
than reading a catalog directory. Accession
fan-out across CIKs is retained; occurrence identity includes source CIK,
accession, and document path.

Target and occurrence-source artifacts are physically unordered in Phase 02.
Identity and provenance fields are retained; later phases may create keys,
indexes, or sorted derivatives. Staging tables are removed after success or
failure and are never included in artifact bundles. Published outputs are
`manifests/filing_extraction/company_profiles/final/company_profiles.parquet`,
`manifests/filing_extraction/filing_occurrence_sources/final/filing_occurrence_sources.parquet`,
and `manifests/filing_extraction/filing_targets/final/form=<key>/data.parquet`.

Fixture-scope plans can be expanded without rerunning Phase 01 or fetching SEC
documents. `expand` creates a new immutable child plan, preserves every parent
locator, and adds locators until the absolute `--target-units` count is met.
The count is for unique document locators; occurrence fan-out is reported
separately. Plans generated after this feature include the effective policy
snapshot and parent identity; legacy plans can be expanded when the compatible
policy is supplied.

## Scope boundary: Phase 02 vs Phase 2.5

Phase 02 only prepares filing metadata for later acquisition. It ends at the
deterministic `filing_targets` catalog and selected target plans; it does not
download, store, or parse raw SEC filing documents.

Filing document acquisition (archive fetch, retries, caching, raw document
storage, parsing, and content extraction) is a separate **Phase 2.5** boundary
that consumes Phase 02 target plans. Phase 2.5 is not implemented here; treat
Phase 02 outputs as the input contract for that future stage.

## How Phase 02 Works

Phase 02 operates as a two-stage, zero-network metadata transformation engine:

```text
Finalized Phase 01 Artifact (submission_metadata.parquet)
                     │
                     ▼
       ┌───────────────────────────┐
       │      1. Materialize       │
       │   - Bounded DuckDB Stream │
       │   - Unnest Filing Arrays  │
       │   - Entity Normalization  │
       │   - Family Clustering     │
       └─────────────┬─────────────┘
                     │
         ┌───────────┴───────────┐
         ▼                       ▼                       ▼
 ┌───────────────┐       ┌───────────────┐       ┌───────────────┐
 │company_profile│       │filing_targets │       │occurrence_srcs│
 └───────┬───────┘       └───────┬───────┘       └───────────────┘
         │                       │
         └───────────┬───────────┘
                     ▼
       ┌───────────────────────────┐
       │         2. Plan           │
       │   - Selection Policy      │
       │   - Family Deduplication  │
       │   - Stratified Allocation │
       └─────────────┬─────────────┘
                     ▼
             Target Plan Artifact
```

1. **Materialization (`materialize`)**:
   - **Zero-Network Invariant**: Reads only the finalized `submission_metadata.parquet` artifact from Phase 01. Never touches transient chunks or makes network requests.
   - **Streaming DuckDB Staging**: Loads CIK rows in configurable memory-bounded batches (default 1,000) into disk-backed DuckDB staging tables.
   - **Unnesting & Provenance**: Expands nested `filings` arrays (`recent` and `historical`) into flat filing occurrences. Retains complete multi-registrant fan-out (when the same accession is filed by multiple CIKs) in `filing_occurrence_sources.parquet`.
   - **Company Family Normalization**: Cleans entity names by stripping state jurisdiction codes (`JURISDICTION_RE`), trademark annotations (`TRADEMARK_RE`), punctuation, and legal suffixes (`family_vocab.py`). Groups related corporate entities into deterministic `company_family` clusters using a two-pass authority index.
   - **Artifact Publication**: Atomically publishes three immutable Parquet datasets:
     - `company_profiles`: Registrant metadata, SIC classifications, and normalized `company_family`.
     - `filing_occurrence_sources`: Full provenance mapping of `(source_cik, accession, document_path)`.
     - `filing_targets`: Hive-partitioned by form (`form=10-K/`, `form=10-Q/`, etc.) containing canonical document paths and filing dates.

2. **Target Planning & Selection (`plan`)**:
   - Evaluates form filters (`target_forms`), era boundaries, and amendment policies (`both`/`original`/`amendments`).
   - Uses `DeficitSelector` to perform stratified, quota-balanced sampling across feature signatures `(company_family, form, era, sic_code, entity_type, lifecycle_class)`.
   - Prevents duplicate over-representation from multiple subsidiaries belonging to the same `company_family`.
   - Emits an immutable `plan.json` snapshot and target manifest.

---

## Expanding Fixtures and Sample Datasets (e.g. 5,000 → 10,000 Locators)

For an existing fixture-scope selection, retain the original plan and expand it:

```bash
.venv/bin/python -m phases.02_filing_extraction.cli expand \
  --parent-plan <plan-5000> --target-units 10000 \
  --selection-policy <selection-policy.json>
```

Then reuse the same Phase 2.5 fixture ID; only missing documents are fetched:

```bash
.venv/bin/python -m phases.025_webpage_storage.cli fill-fixture \
  --plan-dir <plan-10000> --fixture-id <same-fixture-id>
```

Use `--retry-failures` on `fill-fixture` to retry prior acquisition failures.
The fixture sidecar records plan lineage at
`.artifacts/fixtures/<fixture-id>/fixture.manifest.json`.

When expanding the underlying structural sample itself from 500 to 1,000 CIKs:

1. **Define the Target CIK / Record List**:
   - Prepare the expanded 1,000-CIK manifest (e.g. `phases/01_metadata_extraction/tests/fixtures/samples/sample_1000_ciks.json` or sample CSV) with deterministic CIK ordering and input fingerprinting.

2. **Generate the Phase 01 Submission Metadata Fixture**:
   - Run Phase 01 ingestion for the 1,000 sample CIKs into an isolated acceptance workspace:
     ```bash
     .venv/bin/python -m phases.01_metadata_extraction.cli plan \
       --input uploads/cik-sec-1000.csv \
       --artifacts-dir .artifacts/acceptance/phase_01_1000
     .venv/bin/python -m phases.01_metadata_extraction.cli run \
       --artifacts-dir .artifacts/acceptance/phase_01_1000
     .venv/bin/python -m phases.01_metadata_extraction.cli merge \
       --artifacts-dir .artifacts/acceptance/phase_01_1000
     ```

3. **Materialize the Phase 02 Catalog**:
   - Run `materialize` pointing to the finalized Phase 01 artifact:
     ```bash
     .venv/bin/python -m phases.02_filing_extraction.cli materialize \
       --source-artifact .artifacts/acceptance/phase_01_1000/manifests/metadata/submission_metadata/final/submission_metadata.parquet \
       --output-dir .artifacts/acceptance/phase_02_1000
     ```

4. **Plan and Validate Selection Strata**:
   - Generate target plans from the materialized 1,000-record catalog:
     ```bash
     .venv/bin/python -m phases.02_filing_extraction.cli plan \
       --catalog .artifacts/acceptance/phase_02_1000 \
       --form 10-K --form 10-Q
     ```

5. **Verify Invariants and Unit Test Assertions**:
   - Verify schema read-back across `company_profiles`, `filing_targets`, and `filing_occurrence_sources`.
   - Ensure `company_family` deduplication correctly prevents multi-subsidiary duplicate selection in `test_selection.py` and `test_target_plan.py`.
   - Validate that all tests pass:
     ```bash
     .venv/bin/pytest phases/02_filing_extraction/tests
     ```

---

## Handoff and bundles

Phase handoffs use immutable manifests with paths relative to
`ARTIFACTS_ROOT`; no phase assumes another phase's run directory. For
portable finalized inputs, use `python -m defs.runtime.bundle create`, then
`verify` and `import` the bundle at the destination workspace. Bundles do not
include transient chunks or caches.

Selecting Artifact Bundle from `python run.py` opens the same workflow:
choose finalized artifact manifests to bundle, or verify/import an existing
bundle. Subcommands remain available for automation.
