# `edgar_sec.pipelines.document_inventory`

## Purpose

Project filing-cohort observations into accession-level index-page work, capture
and replay `-index.html` responses, and build offline parser-review artifacts.
Layer 4 consumes published `filing_catalog` plans and imports downward only.

## Module layout

| Module | Responsibility |
|---|---|
| `cohort.py` | Validate catalog observations and project selected cohorts into accession work. |
| `discovery.py` | Manifest-only discovery and selection of published plans and fixtures. |
| `fixture_store/` | Mutable local response capture, provenance, discovery, and exact-byte replay; see its [package contract](fixture_store/README.md). |
| `review_artifacts/` | Offline parser review output with inert HTML and deterministic manifests; see its [package contract](review_artifacts/README.md). |
| `snapshot/` | Snapshot schemas, metadata, paths, and current bounded DuckDB anti-join primitives; see its [package contract](snapshot/README.md). |
| `paths.py` | Inventory-specific artifact, runtime, and transient paths; binds index fixtures to the shared foundation resolver. |
| `run_manifest.py` | Path-backed work-order identity and chunk manifest validation. |
| `checkpoint.py` | Transient outcome/entry schemas, attempt commit markers, and resume validation. |
| `broker.py` | Picklable client for the shared SEC broker and typed fetch results. |
| `worker.py` | Per-accession worker task and typed failures. |
| `coordinator.py` | Chunk commit, resume, and retry over bounded work-order batches. |
| `cli.py`, `operator.py` | Fixture/review commands and discovery-driven interactive operations. |
| `run.py` (repository root) | Dispatches the inventory entry to its operator. |

## Contracts

- Fixture capture reuses successful pages and records additional source membership; failed pages remain retryable. Replay validates the response digest and returns exact decompressed bytes. Inventory fixtures live at `{artifacts_root}/document_inventory/fixtures/<fixture_id>/`; their `manifest.json` uses the shared `foundation.runtime.fixtures` envelope, while `details` and the SQLite schema remain inventory-owned.
- Plan and fixture discovery reads manifests only; the operator selects discovered artifacts instead of accepting arbitrary plan JSON paths.
- `engine.index_pages.parser.parse_html_index` transforms explicit bytes to typed domain
  records without network or artifact access; unknown structure never becomes an empty
  successful parse.
- S4 work orders are sorted Parquet relations with validated identity; only one bounded chunk is read into worker memory at a time.
- `run_missing_accessions` returns aggregate run counters and a bounded prefix of per-chunk details, rather than retaining one result object per work-order chunk.
- Snapshot candidate staging writes outcomes, entries, and source-CIK edges incrementally. The anti-join runs in resource-configured DuckDB and emits Parquet relations without collecting full accession keys in Python.

## Command surface

```
python run.py inventory fixture create --fixture ID --catalog-plan PLAN [--limit N]
python run.py inventory fixture fill --fixture ID --catalog-plan PLAN [--limit N]
python run.py inventory fixture list
python run.py inventory review-artifacts --fixture ID --output DIR [--accession ACCESSION]
```

Commands accept `--artifacts` and `--json`; capture also accepts `--limit`, and review
accepts `--workers`, `--limit`, and repeatable `--accession`. Running `python run.py
inventory` opens the discovery-driven fixture/review operator.

## Mirrored tests

`tests/pipelines/document_inventory/`: cohort, fixture store, review artifacts, snapshot,
broker, worker, coordinator, paths, run-manifest, checkpoint, discovery, operator, and CLI tests. Parser tests live in
`tests/engine/index_pages/`; shared contract tests live in `tests/domain/document_inventory/`.

## Deliberate gaps

- The parser has not completed the historical SEC layout audit; final acceptance still
  depends on S0 evidence.
- The S4 coordinator and S5 anti-join staging are not yet integrated into a production
  build command. Full snapshot merging, query APIs, validation, and pointer-last
  publication remain incomplete.
- Cohort projection is in-memory and is suitable for selected offline inputs, not a
  production dataset-scale build boundary; S5 needs a streamed catalog-plan projection.
