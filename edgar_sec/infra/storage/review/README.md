# Review Harness (`edgar_sec.infra.storage.review`)

## Purpose
Reusable harness for parser review runs, multi-format objective diffing, and fixture command delegation across dataset pipelines.

## Guarantees & Contracts
- **Objective Diffing**: Reports strictly what was modified, added, removed, or left unchanged without heuristic assumptions of improvement versus regression.
- **Format-Agnostic Comparison**: Tabular datasets (`.csv`, `.parquet`) are compared via DuckDB SQL set queries; structured JSON is diffed via recursive path flattening; text is diffed line-by-line.
- **Bounded Output**: Console summaries cap displayed case lists with overflow pointers to full persisted JSON manifests.

## Interactive Console

[`run_review_menu`](operator.py) is an interactive console for review runs and fixtures.
It accepts a [`ReviewMenuConfig`](operator.py) and supports:

- **Plan-guided fixtures**: the caller supplies `plans_root` (or `plan_id`);
  create and fill actions display the plan and propose fixture IDs.
- **Paginated pick-lists**: fixture and review-run selection go through
  `prompt_paginated_choice` with a marked default and filtering.
- **Guarded comparison**: fewer than two review runs print a message and return;
  the previous baseline and latest run are the defaults for the base and new
  run prompts.

## Deliberate Gaps
- Pipeline-specific document parsing, SQLite schema definitions, and table extraction logic are owned by the consuming pipeline adapters, not this package.
