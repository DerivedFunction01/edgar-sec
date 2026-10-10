# commands

Layer 4 command handlers for document acquisition.

## Purpose

The package owns the project, run, status, and fixture command implementations. The parent `cli.py` remains responsible for parser registration, output options, placeholders, and process entry.

## Contracts

- **Stable output**: Handlers preserve the CLI's existing JSON and human-readable output shapes and exit codes.
- **Operator delegation**: Handlers retain the same service calls and lazy SEC transport lifecycle used by the CLI and interactive operator.

## Deliberate gaps

- **No parser ownership**: Argument definitions and command registration remain in the parent CLI module.
