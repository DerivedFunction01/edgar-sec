# Review Harness (`edgar_sec.infra.storage.review`)

## Purpose
Reusable harness for parser review runs, multi-format objective diffing, and fixture command delegation across dataset pipelines.

## Module Layout

| Module | Responsibility |
|---|---|
| [`paths.py`](paths.py) | Directory resolvers for review runs, cases, summaries, and patches. |
| [`models.py`](models.py) | Data models for case diff outcomes, component counts, and diff summaries. |
| [`adapter.py`](adapter.py) | Abstract protocol defining pipeline hooks for fixture IO and case comparison. |
| [`diff.py`](diff.py) | Multi-format comparison engine (DuckDB dataset diff, JSON path diff, unified text diff). |
| [`cli.py`](cli.py) | Subparser attachment helper mounting `review` and `fixture` command groups. |
| [`operator.py`](operator.py) | Interactive terminal console for review runs, comparisons, and fixtures. |

## Guarantees & Contracts
- **Objective Diffing**: Reports strictly what was modified, added, removed, or left unchanged without heuristic assumptions of improvement versus regression.
- **Format-Agnostic Comparison**: Tabular datasets (`.csv`, `.parquet`) are compared via DuckDB SQL set queries; structured JSON is diffed via recursive path flattening; text is diffed line-by-line.
- **Bounded Output**: Console summaries cap displayed case lists with overflow pointers to full persisted JSON manifests.

## Public Surface
- [`ReviewPaths`](paths.py)
- [`CaseDiff`](models.py), [`DiffSummary`](models.py)
- [`ReviewAdapter`](adapter.py)
- [`compare_review_runs`](diff.py), [`diff_text`](diff.py), [`diff_json`](diff.py), [`diff_dataset`](diff.py)
- [`attach_review_subparsers`](cli.py)
- [`run_review_menu`](operator.py)

## Mirrored Tests
- [`tests/infra/storage/review/`](../../../../tests/infra/storage/review)

## Deliberate Gaps
- Pipeline-specific document parsing, SQLite schema definitions, and table extraction logic are owned by the consuming pipeline adapters, not this package.
