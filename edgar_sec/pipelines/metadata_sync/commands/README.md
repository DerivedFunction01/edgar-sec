# `edgar_sec.pipelines.metadata_sync.commands` — CLI Subcommand Implementations

Presentation and execution layer for the metadata sync CLI subcommands.

## Purpose

| Concern | Modules |
| :--- | :--- |
| External SEC source refresh and comparison | [sources.py](sources.py) |
| Cohort planning and status reporting | [plan.py](plan.py) |
| Execution and chunk running | [run.py](run.py) |
| Snapshot chunk merging | [merge.py](merge.py) |
| Cohort augmentation | [augment.py](augment.py) |
| Submissions HTTP client factory | [client.py](client.py) |

## Contracts

- Every command returns an integer exit code (0 on success).
- Presentation output is emitted via `render_output` rather than direct JSON prints.
- Unhandled domain exceptions bubble up to `cli.py:main` for uniform exit handling.

## Deliberate Gaps

- Commands do not parse command-line flags or configure argument parsers; argument parsing is owned by [../cli.py](../cli.py).
