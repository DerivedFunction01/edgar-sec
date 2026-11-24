"""Client operator argv host: --op dispatch, operation listing, startup."""

from __future__ import annotations

import json
from typing import Any

from edgar_sec.apps.client import cli
from edgar_sec.apps.client.operator.operator_discovery import (
    help_components,
    listing_components,
    operation_help,
    operation_listing,
)
from edgar_sec.apps.client.operator.operator_execution import (
    OpResult,
    _error_result,
    execute_by_id,
)
from edgar_sec.apps.client.operator.operator_session import ClientSession
from edgar_sec.foundation.runtime.render import render_output


def _print_result(result: OpResult, json_output: bool) -> int:
    if json_output:
        print(json.dumps(result.to_payload(), indent=2))
    else:
        if result.components:
            render_output(result.components, title=result.title)
        if result.error_code:
            print(f"error_code: {result.error_code}")
    return 1 if result.error_code else 0


def _argv_operation(rest: list[str], session: ClientSession) -> int:
    from edgar_sec.apps.client.operator.operator import REGISTRY

    json_output = "--json" in rest
    if not rest or rest[0] in ("--json", "--help", "--options"):
        result = _error_result(
            "object", "invalid_options", "", "an operation id is required"
        )
        return _print_result(result, json_output)
    op_id, tokens = rest[0], rest[1:]
    spec = REGISTRY.get(op_id)
    kind = spec.result_kind if spec is not None else "object"
    if "--help" in tokens or "-h" in tokens:
        if spec is None:
            result = _error_result(
                kind, "unknown_operation", op_id, f"unknown operation: {op_id}"
            )
            return _print_result(result, json_output)
        if json_output:
            print(json.dumps(operation_help(spec), indent=2))
        else:
            render_output(help_components(spec), title="Operation help")
        return 0
    raw_options: dict[str, Any] | None = None
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token == "--json":
            index += 1
        elif token == "--options":
            if index + 1 >= len(tokens):
                result = _error_result(
                    kind, "invalid_options", op_id, "--options needs a JSON value"
                )
                return _print_result(result, json_output)
            try:
                decoded = json.loads(tokens[index + 1])
            except json.JSONDecodeError as exc:
                result = _error_result(kind, "invalid_options", op_id, str(exc))
                return _print_result(result, json_output)
            if not isinstance(decoded, dict):
                result = _error_result(
                    kind, "invalid_options", op_id, "--options must be a JSON object"
                )
                return _print_result(result, json_output)
            raw_options = decoded
            index += 2
        else:
            result = _error_result(
                kind, "invalid_options", op_id, f"unknown argument: {token}"
            )
            return _print_result(result, json_output)
    return _print_result(execute_by_id(op_id, session, raw_options), json_output)


def _argv_dispatch(argv: list[str], session: ClientSession) -> int:
    from edgar_sec.apps.client.operator.operator import REGISTRY

    args = list(argv)
    if args[0] == "--config":
        from edgar_sec.apps.client.operator.operator_config import run_config_argv

        return run_config_argv(args[1:], session)
    if args[0] == "--list-operations":
        rest = args[1:]
        if any(token != "--json" for token in rest):
            result = _error_result(
                "object", "invalid_options", "", "only --json may follow"
            )
            return _print_result(result, "--json" in rest)
        if "--json" in rest:
            print(json.dumps(operation_listing(REGISTRY), indent=2))
        else:
            render_output(listing_components(REGISTRY), title="Operations")
        return 0
    if args[0] == "--op":
        return _argv_operation(args[1:], session)
    return cli.main(args)


def _startup_error() -> str | None:
    """One clear startup refusal, or None when the run may proceed.
    The workspace must resolve and the shipped package data must be present
    at its self-located anchor; either failure is reported once, here.
    """
    from edgar_sec.foundation.runtime.paths import (
        ProjectRootError,
        package_data_status,
        resolve_paths,
    )

    try:
        resolve_paths()
    except ProjectRootError as exc:
        return (
            f"{exc} Name the workspace with the workspace.root setting "
            "(WORKSPACE_ROOT) or run from a directory outside the package."
        )
    status = package_data_status()
    if not status.present:
        return (
            "package data is missing: no taxonomy tree at "
            f"{status.taxonomy_dir} (archive present: {status.archive_dir_present}). "
            "This install is broken; reinstall the package."
        )
    return None
