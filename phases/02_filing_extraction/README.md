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
   output root; produces a catalog directory.
2. Plan filing targets — pick a catalog, optional form filters, an amendment
   policy (`both`/`original`/`amendments`), and an optional limit; writes an
   immutable target-plan directory.
3. Show status — lists discovered catalogs and target plans from their manifests
   and `plan.json` files without scanning Parquet rows or re-fetching source data.
0. Exit

Prompts show workspace-derived defaults. In the standard local layout, blank
materialization input selects the finalized Phase 01
`metadata/runs/local/merge/submission_metadata.parquet` artifact when present,
and blank output inputs use `filing_extraction/catalogs` or
`filing_extraction/runs` under `EDGAR_ARTIFACTS_ROOT`. If exactly one catalog is
available, blank planning input selects it automatically. Materialization and
planning show a tqdm stage bar (source validation, company profiles, per-form
targets, occurrence sources, manifest publication) so long DuckDB and hashing
steps report progress instead of appearing to hang. The canonical CLI accepts an
optional `--progress` flag on `materialize` and `plan` for the same events.

## Canonical command surface

```bash
.venv/bin/python -m phases.02_filing_extraction.cli materialize \
  --source-artifact .artifacts/metadata/runs/local/merge/submission_metadata.parquet
.venv/bin/python -m phases.02_filing_extraction.cli materialize \
  --source-manifest .artifacts/artifact-manifests/<artifact-id>.json
.venv/bin/python -m phases.02_filing_extraction.cli plan --catalog <catalog-directory>
.venv/bin/python -m phases.02_filing_extraction.cli status
```

The catalog records the source artifact hash and schema version. Accession
fan-out across CIKs is retained; occurrence identity includes source CIK,
accession, and document path.

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
`EDGAR_ARTIFACTS_ROOT`; no phase assumes another phase's run directory. For
portable finalized inputs, use `python -m defs.runtime.bundle create`, then
`verify` and `import` the bundle at the destination workspace. Bundles do not
include transient chunks or caches.

Selecting Artifact Bundle from `python run.py` opens the same workflow:
choose finalized artifact manifests to bundle, or verify/import an existing
bundle. Subcommands remain available for automation.
