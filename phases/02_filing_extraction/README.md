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
2. Plan filing targets — pick a catalog, optional form filters, an amendment
   policy (`both`/`original`/`amendments`), and an optional limit; writes an
   immutable target-plan directory.
3. Show status — lists discovered catalogs and target plans from their manifests
   and `plan.json` files without scanning Parquet rows or re-fetching source data.
0. Exit

Prompts show workspace-derived defaults. In the standard local layout, blank
materialization input selects the finalized Phase 01
`manifests/metadata/submission_metadata/final/submission_metadata.parquet` artifact when present,
and blank output inputs use `filing_extraction/catalogs` or
`filing_extraction/runs` under `ARTIFACTS_ROOT`. If exactly one catalog is
available, blank planning input selects it automatically. Materialization and
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
(`filing_extraction.source_batch_size`) and registered through the
`phases/settings.py` barrel; it is a persistable, dataset-relevant setting.
Shared runtime execution settings live in the shared registry
(`defs/runtime/settings/runtime.py`) and are machine-local: they affect how a
machine executes work but are never part of dataset identity, so they default
to machine detection and are not written to config or plans.

Resolution precedence for `source_batch_size`: explicit `--source-batch-size`
flag → direct environment/`.env` (`FILING_EXTRACTION_SOURCE_BATCH_SIZE`) →
persisted Phase 02 config → default. Runtime execution settings resolve as CLI flag →
environment → machine-derived value.

## Canonical command surface

```bash
.venv/bin/python -m phases.02_filing_extraction.cli materialize \
  --source-artifact .artifacts/manifests/metadata/submission_metadata/final/submission_metadata.parquet
.venv/bin/python -m phases.02_filing_extraction.cli materialize \
  --source-manifest .artifacts/manifests/metadata/submission_metadata/final/<artifact-id>.json
.venv/bin/python -m phases.02_filing_extraction.cli plan --catalog <catalog-directory>
.venv/bin/python -m phases.02_filing_extraction.cli status
```

`materialize` accepts machine-tuning overrides: `--source-batch-size`,
`--threads`, `--memory-limit`, `--temp-directory`, and `--progress`. Explicit
flags override the persisted Phase 02 configuration at
`.artifacts/filing_extraction/config.json` (`--config` relocates it), which
currently holds `source_batch_size`; when neither is present the conservative
default (1,000 source rows per batch) applies. DuckDB threads, memory budget,
and spill directory default to machine-derived values (`psutil` with an `os`
fallback) and may be overridden per environment through
`DUCKDB_THREADS`, `DUCKDB_MEMORY_LIMIT`,
`DUCKDB_MEMORY_FRACTION`, and `DUCKDB_TEMP_DIRECTORY` without
touching project configuration. All of these resolve through the shared
settings registry (`defs/runtime/settings/`), not ad-hoc environment reads.

The catalog records the source artifact hash and schema version. Accession
fan-out across CIKs is retained; occurrence identity includes source CIK,
accession, and document path.

Target and occurrence-source artifacts are physically unordered in Phase 02.
Identity and provenance fields are retained; later phases may create keys,
indexes, or sorted derivatives. Staging tables are removed after success or
failure and are never included in artifact bundles.

## Scope boundary: Phase 02 vs Phase 2.5

Phase 02 only prepares filing metadata for later acquisition. It ends at the
deterministic `filing_targets` catalog and selected target plans; it does not
download, store, or parse raw SEC filing documents.

Filing document acquisition (archive fetch, retries, caching, raw document
storage, parsing, and content extraction) is a separate **Phase 2.5** boundary
that consumes Phase 02 target plans. Phase 2.5 is not implemented here; treat
Phase 02 outputs as the input contract for that future stage.

## Handoff and bundles

Phase handoffs use immutable manifests with paths relative to
`ARTIFACTS_ROOT`; no phase assumes another phase's run directory. For
portable finalized inputs, use `python -m defs.runtime.bundle create`, then
`verify` and `import` the bundle at the destination workspace. Bundles do not
include transient chunks or caches.

Selecting Artifact Bundle from `python run.py` opens the same workflow:
choose finalized artifact manifests to bundle, or verify/import an existing
bundle. Subcommands remain available for automation.
