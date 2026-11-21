# xbrl_review

Layer 4 pipeline contract for XBRL semantic review, cohort staging, and hypothesis promotion.

## Purpose

Orchestrates multi-firm XBRL semantic review runs, epistemic quarantine audits, and hypothesis promotion into the canonical DuckDB unification knowledge base. It consumes the pure compute capabilities of `engine.xbrl` to evaluate pre-extracted filing facts and linkbases without performing network I/O.

A projection run starts from a dataset of filing accessions (`project`), is executed by the pipeline's own worker (`execute`) — each filing solved from its seed bundle through the constraint solver, counter-solver, and tokenizer, staged as chunk attempts, and published as a snapshot through the DAG machinery — and can be staged as a review run (`review generate`) whose cases the objective differ compares across runs. Promotion of a candidate hypothesis into the unification knowledge base is gated on recorded census, pair-gate, and battery evidence, and promoted rules load back into the engine knowledge base that later runs are built over.

The package provides both an interactive terminal console with paginated choice selection and a scriptable CLI supporting projection, execution, review artifact generation, objective diffing, gate-evidence computation, and rule promotion.

The package also hosts the FSDS cross-check oracle: a pure comparison pass that
joins solver-parsed facts against Financial Statement Data Sets rows over a
stated panel and reports agreement and divergence classes. FSDS is an oracle
here, never a source of answers.

## Contracts

- **Zero Network Fetching**: This pipeline operates exclusively over pre-extracted filing facts, cohorts, and linkbase bundles; it makes no live requests to SEC EDGAR.
- **Objective Diffing**: Case comparisons report strictly what nodes were modified, added, removed, or left unchanged via the infra storage layer's objective differ.
- **Pure Engine Separation**: Semantic lattice decomposition, ISDA netting derivation, and constraint satisfaction remain in `engine.xbrl`; this pipeline owns only orchestration, staging, and persistence.
- **Atomic Knowledge Base Updates**: Candidate rules are promoted into the DuckDB knowledge base via atomic transactional inserts.
- **Gated Promotion**: A hypothesis promotes only with gate evidence recorded against it; `promote` refuses without passing census, pair-gate, and battery evidence, and promoted rules are loaded by later runs.
- **Dataset-Only Projection**: Projection consumes a uniform dataset (JSON or Parquet) of filing accessions and writes a resumable work order; execution is a separate, explicit step.
- **Self-Describing Quarantine**: The quarantine relation (schema v2) holds one row per (accession, concept) pair: `reason` from the engine's pair-level vocabulary (`QUARANTINE_REASONS` in `engine.xbrl.solve.counter_solver`, decided by exact-qname calc-arc membership and the unconsumed remainder's fact shape), `fact_count` as the pair's unconsumed fact count, and `period`/`numeric_value` from the pair's deterministic representative fact (undimensioned first, then period, value, unit, dimensions, context).
- **FSDS oracle is a pure comparison**: The oracle pass takes FSDS facts, FSDS tag definitions, and solver facts as values and performs no store reads and no network I/O; assembling those inputs from the datasets store and the review bundles is the caller's work, because cross-pipeline imports are limited to paths and schemas.
- **Segments are fact identity in the FSDS join**: Facts join on (accession, concept local name, unit, period end as YYYYMMDD, segments identity). The caller renders both sides into the same canonical segments form (`axis=member` pairs, sorted, `;`-joined); the oracle compares that string opaquely, so a dimensional fact never collapses onto its undimensioned counterpart.
- **Custom tags branch on their version**: Tag semantics resolve through the FSDS tag definitions only. A standard (tag, version) pair joins by local concept name across accessions; a custom tag (`custom=1`) joins only when its version equals the fact's own accession — a custom fact carrying a foreign accession as its version is counted `custom_version_mismatch` and never joined, and a (tag, version) pair with no definition is counted `unresolved_tag`.
- **Oracle outcome classes**: Per accession and panel-wide the pass reports agree / diverge / facts-only / solver-only, with each divergence carrying both sides' value tuples. Non-numeric solver facts are skipped, because FSDS num values are numeric-or-empty; an empty FSDS value diverges against a numeric solver value rather than agreeing with it.

## Deliberate gaps

- **No Raw Document Ingestion**: Acquisition of raw submission bundles and inline XBRL extraction belong to `pipelines.document_acquisition`, not this package.
- **No Direct SEC API Scraping**: Remote filing discovery belongs to `pipelines.filing_catalog` and `pipelines.metadata_sync`.
- **No Catalog-Plan Projection**: Filing-catalog plans carry locator-group aggregates for acquisition planning, not per-filing XBRL work orders, so they are not a projection input; the dataset path is the only one.
- **No Fixture Lifecycle**: Fixture create/fill/list belong to `pipelines.document_acquisition`'s fixture store. XBRL review generation consumes seed bundles resolved from the canonical cohort registry directly, so this package offers no fixture commands.
- **Census Populations Live in the Tools Layer**: The scored census populations are produced by `edgar_sec.tools.xbrl_eval.xbrl_census` through the client facade; this pipeline scores that tool's summary with the engine's census expectations for gate evidence rather than re-implementing the populations.
- **No FSDS serving and no oracle command**: FSDS rows are never served as answers from this package, and the oracle pass has no CLI or operator entry — a drive assembles the store rows and solver facts and calls the comparison directly.

## Command surface

<!-- AUTOGEN:COMMANDS:START -->
| Subcommand | Description | Arguments |
| :--- | :--- | :--- |
| `dag` | Snapshot DAG operations | `[--root]`, `[--json]` |
| `execute` | execute a projected run | `--run-id`, `[--artifacts]`, `[--json]` |
| `project` | project a dataset into a resumable run | `--dataset`, `[--queries]`, `[--base-snapshot-id]`, `[--branch]`, `[--explicit-refresh]`, `[--chunk-size]`, `[--artifacts]`, `[--json]` |
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
│           │       │   ├── calculation_arcs.parquet
│           │       │   ├── hypotheses.parquet
│           │       │   ├── manifest.json
│           │       │   ├── presentation_arcs.parquet
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
    ├── fixtures/  # Root directory for XBRL fixture stores.
    │   └── {fixture_id}/  # Root directory for one XBRL fixture.
    │       ├── fixture.sqlite
    │       └── manifest.json
    ├── review-runs/
    │   └── {run_id}/
    │       ├── cases/
    │       │   └── {accession}/
    │       │       ├── calculation_arcs.parquet
    │       │       ├── hypotheses.parquet
    │       │       ├── presentation_arcs.parquet
    │       │       ├── quarantine.parquet
    │       │       ├── rule_trace.parquet
    │       │       └── solved_nodes.parquet
    │       └── manifest.jsonl
    ├── snapshots/
    │   ├── {snapshot_id}/
    │   │   └── {relation}/
    │   │       └── part-{part_index}.parquet
    │   ├── .publication.lock
    │   └── catalog.sqlite  # SQLite DAG catalog database for published XBRL snapshots.
    └── unification_rules.duckdb
```
<!-- AUTOGEN:PATHS:END -->
