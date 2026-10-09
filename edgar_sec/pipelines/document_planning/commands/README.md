# `document_planning/commands`

## Purpose

Bind CLI arguments to the document-planning pipeline and render concise results.

## Layout

| Module | Responsibility |
| :--- | :--- |
| `__init__.py` | Package marker. |
| `plan.py` | Publish a target plan from selected evidence. |
| `inspect.py` | Validate and report a published plan. |
| `status.py` | List profiles and manifest-level plan status. |

## Contracts

Commands are offline and do not project inventory or start document acquisition.
Interactive confirmation belongs to the operator; direct CLI planning is explicit.

## Public surface

The CLI binds the `cmd_*` handlers from their owning modules.

## Command surface

See the parent [`document_planning`](../README.md) package.

## Mirrored tests

`tests/pipelines/document_planning/commands/`.

## Deliberate gaps

No acquisition, inventory projection, or source refresh command is provided.
