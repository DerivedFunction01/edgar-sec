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

## Layout

| Module | Responsibility |
| :--- | :--- |
| [common.py](common.py) | Shared argument resolver and progress callback adapter. |
| [materialize.py](materialize.py) | `cmd_materialize`. |
| [plan.py](plan.py) | `cmd_plan`, `_load_policy`. |
| [expand.py](expand.py) | `cmd_expand`. |
| [status.py](status.py) | `cmd_status`. |
| `__init__.py` | Package docstring only; no re-exports. |

## Contracts

- Every command returns an integer exit code (0 on success, 1 on error).
- Presentation output is formatted with `render_output` components (`KeyValueRow`).
- Catchable pipeline exceptions print clean error lines to `sys.stderr` and return 1.

## Public Surface

- [materialize.py](materialize.py): `cmd_materialize`
- [plan.py](plan.py): `cmd_plan`
- [expand.py](expand.py): `cmd_expand`
- [status.py](status.py): `cmd_status`

## Mirrored Tests

Mirrored tests live under `tests/pipelines/filing_catalog/commands/`.

## Deliberate Gaps

- Commands accept an `argparse.Namespace` and do not configure CLI argument parsers directly; parsers are defined in [../cli.py](../cli.py).
