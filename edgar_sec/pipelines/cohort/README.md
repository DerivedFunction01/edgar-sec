# `edgar_sec/pipelines/cohort`

## Purpose

Provides Phase 0 command-line and interactive orchestration for the shared cohort catalog before metadata collection.

## Contracts

- Cohort references are resolved by `CohortCatalog.resolve_cohort_identifier()`;
  short, missing, and ambiguous identifiers fail with a nonzero command status.
- Cohort data and workspace state use the shared Layer 2 cohort paths and catalog.
- Workspace session expiry is swept by commands using the standard CLI context;
  `doctor` and `maintain` bypass that context and do not touch session state.
- Membership is unique by CIK. File duplicates choose the first non-empty trimmed
  input-row name; union/intersection use the left non-empty name, then the right.
  Put official SEC sources on the left to prioritize their labels. Blank names
  fall through and never produce duplicate members.
- Interactive cohort, workspace, and upload selection is paginated and filterable;
  headless list, query, and find results use aligned tables.
- Official SEC source refresh is owned here; `diff` accepts cohort IDs/names and
  the active `universe`/`tickers` aliases, with optional canonical delta publication.

## Command Surface

<!-- AUTOGEN:COMMANDS:START -->
| Subcommand | Description | Arguments |
| :--- | :--- | :--- |
| `console` | open the interactive cohort console | — |
| `delete` | delete a cohort | `[--keep-dataset]` |
| `diff` | compare cohort membership | `[--save-left-delta]`, `[--save-right-delta]` |
| `doctor` | audit catalog and cohort artifacts read-only | — |
| `family-index` | publish the active universe family index | — |
| `find` | search members across cohorts | `[--cik]`, `[--name]`, `[--limit]`, `[--page]` |
| `import` | import a delimited, text, or Parquet file | `--input`, `[--name]`, `[--tags]`, `[--delimiter]`, `[--limit]` |
| `info` | show cohort metadata and sample members | — |
| `list` | list catalog cohorts | `[--tag]`, `[--pinned-only]`, `[--search]`, `[--limit]`, `[--offset]` |
| `maintain` | explicitly clean cohort artifacts | `[--clean-stale-staging]`, `[--clean-orphans]`, `[--clean-missing]`, `[--clean-detached]`, `[--clean-raw-snapshots]`, `[--all]`, `[--force]` |
| `merge` | evaluate a cohort set expression | `--expr`, `[--name]`, `[--tags]`, `[--serialize]` |
| `query` | query members of one cohort | `[--cik]`, `[--name]`, `[--limit]`, `[--offset]` |
| `rename` | rename a cohort | `--name` |
| `repl` | open an interactive cohort workspace | — |
| `sample` | create a deterministic cohort sample | `--source`, `[--method]`, `[--rate]`, `[--limit]`, `[--seed]`, `[--group-family]`, `[--family-index]`, `[--exclude-spv]`, `[--name]` |
| `sources` | manage official SEC source cohorts | — |
| `tag` | add or remove cohort tags | `[--add]`, `[--remove]` |
| `untag` | remove cohort tags | `--tags` |
| `workspace` | manage workspace sessions and variables | — |
<!-- AUTOGEN:COMMANDS:END -->

### Usage examples

```bash
# List cohorts and inspect a specific one
python run.py cohort list --tag public
python run.py cohort info --cik 0000320193

# Import a new cohort from CSV
python run.py cohort import --input companies.csv --name my-cohort --tags curated

# Find companies by CIK across all cohorts
python run.py cohort find --cik 0000320193 --limit 10

# Create a sample cohort from an existing one
python run.py cohort sample --source my-cohort --method random --rate 0.1 --seed 42

# Refresh official SEC source cohorts
python run.py cohort sources refresh
```

## Deliberate Gaps

- Family-grouped sampling requires the caller to pass `--family-index`; it does not
  fall back to the active family-index pointer.
