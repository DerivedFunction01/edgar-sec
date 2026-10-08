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
- [`ReviewMenuConfig`](operator.py), [`run_review_menu`](operator.py)

## Interactive Console

[`run_review_menu`](operator.py) is an interactive console for review runs and fixtures.
It accepts a [`ReviewMenuConfig`](operator.py) and supports:

- **Plan-guided fixtures**: the caller supplies `plan_id_provider` (a callback the
  owning pipeline layer resolves into plan metadata); create and fill actions
  display the plan and propose `fx_{plan_id[:8]}` fixture IDs.
- **Paginated pick-lists**: fixture and review-run selection go through
  `prompt_paginated_choice` with a marked default and filtering.
- **Guarded comparison**: fewer than two review runs print a message and return;
  the previous baseline and latest run are the defaults for the base and new
  run prompts.

## Mirrored Tests
- [`tests/infra/storage/review/`](../../../../tests/infra/storage/review)

## Deliberate Gaps
- Pipeline-specific document parsing, SQLite schema definitions, and table extraction logic are owned by the consuming pipeline adapters, not this package.
