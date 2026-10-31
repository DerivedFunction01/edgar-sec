# xbrl_review

Layer 4 pipeline contract for XBRL semantic review, cohort staging, and hypothesis promotion.

## Purpose

Orchestrates multi-firm XBRL semantic review runs, epistemic quarantine audits, and hypothesis promotion into the canonical DuckDB unification knowledge base. It consumes the pure compute capabilities of `engine.xbrl` to evaluate pre-extracted filing facts and linkbases without performing network I/O.

A projection run starts from a dataset of filing accessions (`project`), is executed by the pipeline's own worker (`execute`) — each filing solved from its seed bundle through the constraint solver, counter-solver, and tokenizer, staged as chunk attempts, and published as a snapshot through the DAG machinery — and can be staged as a review run (`review generate`) whose cases the objective differ compares across runs. Promotion of a candidate hypothesis into the unification knowledge base is gated on recorded census, pair-gate, and battery evidence, and promoted rules load back into the engine knowledge base that later runs are built over.

The package provides both an interactive terminal console (`operator.py`) with paginated choice selection and a scriptable CLI (`cli.py`) supporting projection, execution, review artifact generation, objective diffing, gate-evidence computation, and rule promotion.

## Contracts

- **Zero Network Fetching**: This pipeline operates exclusively over pre-extracted filing facts, cohorts, and linkbase bundles; it makes no live requests to SEC EDGAR.
- **Objective Diffing**: Case comparisons report strictly what nodes were modified, added, removed, or left unchanged via `infra.storage.review.diff.diff_json`.
- **Pure Engine Separation**: Semantic lattice decomposition, ISDA netting derivation, and constraint satisfaction remain in `engine.xbrl`; this pipeline owns only orchestration, staging, and persistence.
- **Atomic Knowledge Base Updates**: Candidate rules are promoted into the DuckDB knowledge base via atomic transactional inserts.
- **Gated Promotion**: A hypothesis promotes only with gate evidence recorded against it; `promote` refuses without passing census, pair-gate, and battery evidence, and promoted rules are loaded by later runs.
- **Dataset-Only Projection**: Projection consumes a uniform dataset (JSON or Parquet) of filing accessions and writes a resumable work order; execution is a separate, explicit step.
- **Self-Describing Quarantine**: The quarantine relation (schema v2) holds one row per (accession, concept) pair: `reason` from the engine's pair-level vocabulary (`QUARANTINE_REASONS` in `engine.xbrl.solve.counter_solver`, decided by exact-qname calc-arc membership and the unconsumed remainder's fact shape), `fact_count` as the pair's unconsumed fact count, and `period`/`numeric_value` from the pair's deterministic representative fact (undimensioned first, then period, value, unit, dimensions, context).

## Deliberate gaps

- **No Raw Document Ingestion**: Acquisition of raw submission bundles and inline XBRL extraction belong to `pipelines.document_acquisition`, not this package.
- **No Direct SEC API Scraping**: Remote filing discovery belongs to `pipelines.filing_catalog` and `pipelines.metadata_sync`.
- **No Catalog-Plan Projection**: Filing-catalog plans carry locator-group aggregates for acquisition planning, not per-filing XBRL work orders, so they are not a projection input; the dataset path is the only one.
- **No Fixture Lifecycle**: Fixture create/fill/list belong to `pipelines.document_acquisition`'s fixture store. XBRL review generation consumes seed bundles resolved from the canonical cohort registry directly, so this package offers no fixture commands.
- **Census Populations Live in the Tools Layer**: The scored census populations are produced by `edgar_sec.tools.xbrl_census` through the client facade; this pipeline scores that tool's summary with the engine's census expectations for gate evidence rather than re-implementing the populations.

## Command surface

<!-- AUTOGEN:COMMANDS:START -->
| Subcommand | Description | Arguments |
| :--- | :--- | :--- |
| `dag` | Snapshot DAG operations | `[--root]`, `[--json]` |
| `execute` | execute a projected run | `[--run-id]`, `[--artifacts]`, `[--json]` |
| `project` | project a dataset into a resumable run | `[--dataset]`, `[--queries]`, `[--base-snapshot-id]`, `[--branch]`, `[--explicit-refresh]`, `[--chunk-size]`, `[--artifacts]`, `[--json]` |
| `review` | generate and compare review runs with pipeline-specific commands | — |
<!-- AUTOGEN:COMMANDS:END -->

### Usage examples

```bash
# Launch interactive review and staging operator console
.venv/bin/python run.py xbrl

# Project the canonical seed registry into a resumable work order
.venv/bin/python run.py xbrl project --dataset tests/fixtures/xbrl/seed_cohort.json

# Execute the projected run and publish its snapshot
.venv/bin/python run.py xbrl execute --run-id run-20261026_120000

# Generate review artifacts from the seed cohort bundles
.venv/bin/python run.py xbrl review generate --fixture seed

# Compare two review runs
.venv/bin/python run.py xbrl review compare --base .artifacts/xbrl/review-runs/run-20261026_120000 --new .artifacts/xbrl/review-runs/run-20261026_130000

# Compute the gate evidence promotion requires
.venv/bin/python run.py xbrl review gates --output gate_evidence.json --census-summary census_summary.json

# Promote a candidate hypothesis rule into the DuckDB knowledge base
.venv/bin/python run.py xbrl review promote --rule-id HYP_SHADOW_0000950170-24-087843_0 --run-dir .artifacts/xbrl/review-runs/run-20261026_120000 --evidence gate_evidence.json

# Inspect DAG status and branch tip
.venv/bin/python run.py xbrl dag status
```

## Artifact layout

<!-- AUTOGEN:PATHS:START -->
```text
{artifacts_root}/
├── transient/
│   └── xbrl/
│       └── {run_id}/
│           ├── chunks/
│           │   └── {chunk_id}/
│           │       ├── attempt-{attempt_id}/
│           │       │   ├── hypotheses.parquet
│           │       │   ├── manifest.json
│           │       │   ├── quarantine.parquet
│           │       │   ├── rule_trace.parquet
│           │       │   └── solved_nodes.parquet
│           │       └── current.json
│           ├── cohort_accessions.parquet
│           ├── projection_manifest.json
│           ├── run.lock
│           ├── run_manifest.json
│           └── work_order.parquet
└── xbrl/
    ├── review-runs/
    │   └── {run_id}/
    │       ├── cases/
    │       │   └── {accession}/
    │       │       ├── hypotheses.parquet
    │       │       ├── quarantine.parquet
    │       │       ├── rule_trace.parquet
    │       │       └── solved_nodes.parquet
    │       └── manifest.jsonl
    ├── snapshots/
    │   ├── {snapshot_id}/
    │   │   ├── hypotheses/
    │   │   │   └── part-00000.parquet
    │   │   ├── quarantine/
    │   │   │   └── part-00000.parquet
    │   │   ├── rule_trace/
    │   │   │   └── part-00000.parquet
    │   │   └── solved_nodes/
    │   │       └── part-00000.parquet
    │   ├── .publication.lock
    │   └── catalog.sqlite  # SQLite DAG catalog database for published XBRL snapshots.
    └── unification_rules.duckdb
```
<!-- AUTOGEN:PATHS:END -->
