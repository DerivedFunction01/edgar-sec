# `edgar_sec.pipelines.filing_catalog.commands` — CLI Subcommand Implementations

Presentation and execution layer for the filing catalog CLI subcommands.

## Purpose

| Concern | Modules |
| :--- | :--- |
| Catalog materialization from metadata snapshot | [materialize.py](materialize.py) |
| Deterministic and policy-driven catalog planning | [plan.py](plan.py) |
| Policy plan scaling and locator expansion | [expand.py](expand.py) |
| Catalog and plan status reporting | [status.py](status.py) |
| Shared command-line argument resolution and progress | [common.py](common.py) |

## Contracts

- Every command returns an integer exit code (0 on success, 1 on error).
- Presentation output is formatted with `render_output` components (`KeyValueRow`).
- Catchable pipeline exceptions print clean error lines to `sys.stderr` and return 1.
- Commands are dispatch handlers only; they receive pre-parsed `argparse.Namespace` objects and do not configure their own argument parsers.

## Deliberate Gaps

- CLI entry points, argument parsing, and top-level help are owned by [../cli.py](../cli.py).
