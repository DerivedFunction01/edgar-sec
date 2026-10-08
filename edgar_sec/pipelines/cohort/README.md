# `edgar_sec/pipelines/cohort`

## Purpose

Provides Phase 0 command-line and interactive orchestration for the shared cohort catalog before metadata collection.

## Module Map

| Module | Responsibility |
| :--- | :--- |
| `options.py` | CLI grammar and argument validation. |
| `menu.py` | Grouped interactive console and prompt flows. |
| `cli.py` | Catalog, query, sampling, expression, and workspace command dispatch. |
| `__init__.py` | Package docstring only; no re-exports. |

## Contracts

- Cohort references are resolved by `CohortCatalog.resolve_cohort_identifier()`;
  short, missing, and ambiguous identifiers fail with a nonzero command status.
- Cohort data and workspace state use the shared Layer 2 cohort paths and catalog.
- Workspace session expiry is swept on CLI startup.
- Membership is unique by CIK. File duplicates choose the first non-empty trimmed
  input-row name; union/intersection use the left non-empty name, then the right.
  Put official SEC sources on the left to prioritize their labels. Blank names
  fall through and never produce duplicate members.

## Public Surface

- `main()` in [`cli.py`](cli.py) is the launcher entry point.
- `build_parser()` in [`options.py`](options.py) exposes the documented command grammar.

## Command Surface

`import`, `list`, `info`, `rename`, `tag`, `untag`, `delete`, `query`, `find`,
`sample`, `workspace`, `merge`, and `console`.

## Mirrored Tests

`tests/pipelines/cohort/`.

## Deliberate Gaps

- Family-grouped sampling requires the caller to pass `--family-index` because
  the cohort layer does not build or implicitly resolve metadata family indexes.
- Interactive family assignment remains available through
  `edgar-sec metadata family-index`.
