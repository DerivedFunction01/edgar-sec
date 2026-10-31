# commands

Layer 4 command handlers for document acquisition.

## Purpose

The package owns project, run, fixture, and review command handlers. The parent `cli.py` registers acquisition-specific fixture actions and the shared review generate/compare console; it also owns output options, gated placeholders, and process entry.

## Contracts

- **Stable output**: Handlers preserve the CLI's existing JSON and human-readable output shapes and exit codes.
- **Operator delegation**: Handlers retain the same service calls and lazy SEC transport lifecycle used by the CLI and interactive operator.
- **Review output**: Review generation uses the shared manifest/case layout and records per-case artifact digests; comparison delegates to the shared review console.

## Deliberate gaps

- **No parser ownership**: Argument definitions and command registration remain in the parent CLI module.
