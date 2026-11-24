"""Client operator: a held session, one operation registry, and its hosts.

Rows execute against ``ClientSession``; the menu host holds one session and
the argv host builds an ephemeral one, falling back to the fetch CLI branch.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from typing import Any

from edgar_sec.apps.client import cli
from edgar_sec.apps.client.operator.operator_discovery import (
    help_components,
    listing_components,
    operation_help,
    operation_listing,
)
from edgar_sec.apps.client.operator.operator_execution import (
    execute_by_id,
    execute_operation,
)
from edgar_sec.apps.client.operator.operator_registry import GATHERERS, REGISTRY
from edgar_sec.apps.client.operator.operator_results import OpResult, _error_result
from edgar_sec.apps.client.operator.operator_session import ClientSession
from edgar_sec.apps.client.operator.operator_specs import OperationSpec
from edgar_sec.foundation.runtime.interactive import (
    MenuAction,
    MenuSeparator,
    build_menu,
    menu_action,
    operator_entrypoint,
    prompt_text,
)
from edgar_sec.foundation.runtime.render import render_output

__all__ = [
    "build_operator_menu",
    "main",
    "render_session_header",
]


MENU_TITLE = "Filing Runner & Fetch"


INTERRUPTED_MESSAGE = "Action cancelled by user."


def render_session_header(session: ClientSession) -> str:
    """The per-loop header: mode, snapshot, current set and filing."""
    current = session.current_set
    count = len(current) if current is not None else 0
    filing = session.current_filing.accession if session.current_filing else "none"
    snapshot = session.read_context.snapshot or "none"
    name = session.current_set_name or "none"
    return (
        f"mode: {session.read_context.mode} · snapshot: {snapshot} · "
        f"current set: {name} ({count}) · current filing: {filing}"
    )


def _run_and_render(spec: OperationSpec, session: ClientSession) -> None:
    gatherer = GATHERERS.get(spec.id)
    if gatherer is not None and session.satisfies(spec.requires):
        try:
            options = gatherer(session)
        except ValueError as exc:
            result = _error_result(
                spec.result_kind, "invalid_options", spec.label, str(exc)
            )
        except Exception as exc:  # noqa: BLE001 - a gather failure is a coded result
            result = _error_result(
                spec.result_kind, "external_failure", spec.label, str(exc)
            )
        else:
            result = execute_operation(spec, session, options)
    else:
        result = execute_operation(spec, session)
    if result.components:
        render_output(result.components, title=result.title)
    if result.error_code:
        print(f"error_code: {result.error_code}")


def _prompt_operation_help(registry: Mapping[str, OperationSpec]) -> None:
    op_id = prompt_text("Operation id", "").strip()
    spec = registry.get(op_id)
    if spec is None:
        print("error_code: unknown_operation")
        return
    render_output(help_components(spec), title="Operation help")


def build_operator_menu(
    session: ClientSession,
    registry: Mapping[str, OperationSpec] | None = None,
) -> tuple[MenuAction | MenuSeparator, ...]:
    """Build the menu; requirement-gated rows stay listed, availability hides."""
    specs = REGISTRY if registry is None else registry
    actions: list[MenuAction | MenuSeparator] = [MenuSeparator("Operations")]
    for spec in specs.values():
        if spec.available is None or spec.available(session):
            actions.append(
                menu_action(
                    spec.label,
                    lambda spec=spec, session=session: _run_and_render(spec, session),
                )
            )
    actions.append(MenuSeparator("Discovery"))
    actions.append(
        menu_action(
            "List operations",
            lambda: render_output(listing_components(specs), title="Operations"),
        )
    )
    actions.append(menu_action("Operation help", lambda: _prompt_operation_help(specs)))
    return build_menu(*actions)


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


def main(argv: list[str] | None = None, *, session: ClientSession | None = None) -> int:
    """Operator entrypoint: menu with no arguments, argv host otherwise."""
    if (error := _startup_error()) is not None:
        print(error, file=sys.stderr)
        return 2
    held = session or ClientSession()
    return operator_entrypoint(
        MENU_TITLE,
        lambda: build_operator_menu(held),
        lambda args: _argv_dispatch(args, held),
        argv,
        interrupted_message=INTERRUPTED_MESSAGE,
        before_menu=lambda: render_session_header(held),
    )


if __name__ == "__main__":
    # runpy re-execution splits module identity, so delegate to the
    # canonically imported module whose OpResult sibling rows build.
    from edgar_sec.apps.client.operator.operator import main as _canonical_main

    sys.exit(_canonical_main())
