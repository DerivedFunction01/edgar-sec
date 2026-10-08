# `edgar_sec/pipelines/cohort`

## Purpose

Provides Phase 0 command-line and interactive orchestration for the shared cohort catalog before metadata collection.

## Module Map

| Module | Responsibility |
| :--- | :--- |
| `options.py` | CLI grammar and argument validation. |
| `menu.py` | Grouped interactive console and prompt flows. |
| `cli.py` | Cohort catalog, doctor/maintenance, source refresh, diff, sampling, family-index, and workspace dispatch. |
| `repl.py` | Line-oriented workspace commands and set-expression assignments. |
| `family_index.py` | Content-addressed publication of the active universe family index. |
| `__init__.py` | Package docstring only; no re-exports. |

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

## Public Surface

- `main()` in [`cli.py`](cli.py) is the launcher entry point.
- `build_parser()` in [`options.py`](options.py) exposes the documented command grammar.
- `run_repl()` in [`repl.py`](repl.py) runs the opt-in interactive workspace.

## Command Surface

`import`, `list`, `info`, `rename`, `tag`, `untag`, `delete`, `query`, `find`,
`sample`, `sources refresh`, `diff`, `family-index`, `doctor`, `maintain`,
`workspace`, `merge`, `repl`, and `console`.

## Mirrored Tests

`tests/pipelines/cohort/`.

## Deliberate Gaps

- Family-grouped sampling requires the caller to pass `--family-index`; it does not
  fall back to the active family-index pointer.
