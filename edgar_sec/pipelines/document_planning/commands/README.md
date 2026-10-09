# `document_planning/commands`

## Purpose

Bind CLI arguments to the document-planning pipeline and render concise results.

## Contracts

Commands are offline and do not project inventory or start document acquisition.
Interactive confirmation belongs to the operator; direct CLI planning is explicit.
Commands are dispatch handlers only; they receive pre-parsed `argparse.Namespace` objects and do not configure their own argument parsers.

## Deliberate gaps

- CLI entry points, argument parsing, and top-level help are owned by [../cli.py](../cli.py).
- No acquisition, inventory projection, or source refresh command is provided.
