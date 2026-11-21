# document_inventory.commands — Command Implementations

## Purpose

Terminal subcommand implementations for the document inventory pipeline.

## Contracts

- Commands are dispatch handlers only; they receive pre-parsed `argparse.Namespace` objects and do not configure their own argument parsers.

## Deliberate Gaps

- CLI entry points, argument parsing, and top-level help are owned by [../cli.py](../cli.py).
- **No interactive prompts.** Prompts and menus are owned by `operator.py`.
- **JSON and terminal text only.** Output formatting stays in command handlers; prompts and menus are owned by `operator.py`.
