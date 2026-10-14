# xbrl_review

Layer 4 pipeline contract for XBRL semantic review, cohort staging, and hypothesis promotion.

## Purpose

Orchestrates multi-firm XBRL semantic review runs, epistemic quarantine audits, and hypothesis promotion into the canonical DuckDB unification knowledge base. It consumes the pure compute capabilities of `engine.xbrl` to evaluate pre-extracted filing facts and linkbases without performing network I/O.

The package provides both an interactive terminal console (`operator.py`) with paginated choice selection and a scriptable CLI (`cli.py`) supporting review artifact generation, multi-format objective diffing, and rule promotion.

## Contracts

- **Zero Network Fetching**: This pipeline operates exclusively over pre-extracted filing facts, cohorts, and linkbase bundles; it makes no live requests to SEC EDGAR.
- **Objective Diffing**: Case comparisons report strictly what nodes were modified, added, removed, or left unchanged via `infra.storage.review.diff.diff_json`.
- **Pure Engine Separation**: Semantic lattice decomposition, ISDA netting derivation, and constraint satisfaction remain in `engine.xbrl`; this pipeline owns only orchestration, staging, and persistence.
- **Atomic Knowledge Base Updates**: Candidate rules are promoted into the DuckDB knowledge base via atomic transactional inserts.

## Deliberate gaps

- **No Raw Document Ingestion**: Acquisition of raw submission bundles and inline XBRL extraction belong to `pipelines.document_acquisition`, not this package.
- **No Direct SEC API Scraping**: Remote filing discovery belongs to `pipelines.filing_catalog` and `pipelines.metadata_sync`.

## Command surface

<!-- AUTOGEN:COMMANDS:START -->
<!-- AUTOGEN:COMMANDS:END -->

### Usage examples

```bash
# Launch interactive review and staging operator console
.venv/bin/python run.py xbrl

# Run robustness benchmark across S&P 100 cohort
.venv/bin/python run.py xbrl benchmark --cohort-file tests/fixtures/xbrl/sp100_cohort.json

# Generate review artifacts from seed cohort
.venv/bin/python run.py xbrl review generate --fixture seed

# Compare two review runs
.venv/bin/python run.py xbrl review compare --base .artifacts/xbrl/review-runs/run-20261014_120000 --new .artifacts/xbrl/review-runs/run-20261014_130000

# Promote candidate hypothesis rule into DuckDB knowledge base
.venv/bin/python run.py xbrl review promote --rule-id HYP_SHADOW_0000950170-24-087843_0 --run-dir .artifacts/xbrl/review-runs/run-20261014_120000
```

## Artifact layout

<!-- AUTOGEN:PATHS:START -->
<!-- AUTOGEN:PATHS:END -->
