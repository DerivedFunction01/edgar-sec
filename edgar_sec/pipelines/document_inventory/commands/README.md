# document_inventory.commands — Command Implementations

## Purpose

Terminal subcommand implementations for the document inventory pipeline using structured components.

## Layout

| Module | Responsibility |
| :--- | :--- |
| `__init__.py` | Package docstring only. |
| `common.py` | Shared artifact path resolution, plan resolution, and cohort projection. |
| `fixture.py` | `cmd_fixture_create`, `cmd_fixture_fill`, and `cmd_fixture_list`. |
| `review.py` | `cmd_review_artifacts` building offline parser review bundles. |
| `build.py` | `cmd_build` orchestrating inventory snapshot publication. |
| `query.py` | `cmd_query` executing point and range lookups against snapshots. |

## Public Surface

| Entry point | Module |
| :--- | :--- |
| `cmd_fixture_create` | `fixture.py` |
| `cmd_fixture_fill` | `fixture.py` |
| `cmd_fixture_list` | `fixture.py` |
| `cmd_review_artifacts` | `review.py` |
| `cmd_build` | `build.py` |
| `cmd_query` | `query.py` |

## Mirrored Tests

Mirrored tests live under `tests/pipelines/document_inventory/commands/`.

## Deliberate Gaps

- **No interactive prompts.** Prompts and menus are owned by `operator.py`.
- **JSON and component rendering only.** Output formatting is strictly JSON or structured components.
