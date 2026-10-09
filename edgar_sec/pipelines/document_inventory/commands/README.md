# document_inventory.commands — Command Implementations

## Purpose

Terminal subcommand implementations for the document inventory pipeline.

## Layout

| Module | Responsibility |
| :--- | :--- |
| `__init__.py` | Package docstring only. |
| `common.py` | Shared artifact, plan, and fixture-cohort resolution. |
| `project.py` | `cmd_project` projects a published catalog plan without network access. |
| `run.py` | `cmd_run` executes pending S4 chunks and persists cancellation state. |
| `status.py` | `cmd_status` reports validated persisted run state without repair. |
| `publish.py` | `cmd_publish` validates and publishes a completed run without network access. |
| `fixture.py` | `cmd_fixture_create`, `cmd_fixture_fill`, and `cmd_fixture_list`. |
| `review.py` | `cmd_review_artifacts` building offline parser review bundles. |
| `query.py` | `cmd_query` executing point and range lookups against snapshots. |

## Public Surface

| Entry point | Module |
| :--- | :--- |
| `cmd_fixture_create` | `fixture.py` |
| `cmd_fixture_fill` | `fixture.py` |
| `cmd_fixture_list` | `fixture.py` |
| `cmd_review_artifacts` | `review.py` |
| `cmd_query` | `query.py` |
| `cmd_project` | `project.py` |
| `cmd_run` | `run.py` |
| `cmd_status` | `status.py` |
| `cmd_publish` | `publish.py` |

The approved public lifecycle commands are `inventory project`, `inventory run`,
`inventory status`, and `inventory publish`. Project pins the base; Run performs
network work; Status is read-only; Publish performs no network work and requires
the target branch tip to equal the run's pinned base. The DAG Publish action selects
an existing run and invokes Publish.

## Mirrored Tests

Mirrored tests live under `tests/pipelines/document_inventory/commands/`.

## Deliberate Gaps

- **No interactive prompts.** Prompts and menus are owned by `operator.py`.
- **JSON and terminal text only.** Output formatting stays in command handlers; prompts
  and menus are owned by `operator.py`.
