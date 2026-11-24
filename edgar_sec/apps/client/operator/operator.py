"""Client operator: a held session, one operation registry, and its hosts.

Rows execute against ``ClientSession``; the menu host holds one session and
the argv host builds an ephemeral one, falling back to the fetch CLI branch.
"""

from __future__ import annotations

import sys
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from edgar_sec.apps.client.operator.operator_argv import (
    _argv_dispatch,
    _startup_error,
)
from edgar_sec.apps.client.operator.operator_discovery import (
    help_components,
    listing_components,
)
from edgar_sec.apps.client.operator.operator_execution import (
    OpResult,
    OperationSpec,
    _error_result,
    execute_operation,
)
from edgar_sec.apps.client.operator.operator_session import ClientSession
from edgar_sec.foundation.runtime.interactive import (
    MenuAction,
    MenuSeparator,
    build_menu,
    menu_action,
    operator_entrypoint,
    prompt_text,
)
from edgar_sec.foundation.runtime.render import (
    KeyValueRow,
    RenderComponent,
    render_output,
)

__all__ = [
    "GATHERERS",
    "REGISTRY",
    "SessionSummaryOptions",
    "assemble_registry",
    "build_operator_menu",
    "main",
    "render_session_header",
]


MENU_TITLE = "Filing Runner & Fetch"


INTERRUPTED_MESSAGE = "Action cancelled by user."


@dataclass(frozen=True, slots=True)
class SessionSummaryOptions:
    """Options for the session summary row."""

    include_sets: bool = field(
        default=True,
        metadata={
            "help": "Selects whether named working sets are listed with their "
            "counts. No refusal rules apply."
        },
    )


def _execute_session_summary(
    options: SessionSummaryOptions, session: ClientSession
) -> OpResult:
    current = session.current_set
    filing = session.current_filing.accession if session.current_filing else ""
    data: dict[str, Any] = {
        "mode": session.read_context.mode,
        "snapshot": session.read_context.snapshot,
        "current_set": session.current_set_name,
        "current_set_count": len(current) if current is not None else 0,
        "current_filing": filing,
        "set_count": len(session.sets),
    }
    rows: list[RenderComponent] = [
        KeyValueRow("mode", data["mode"]),
        KeyValueRow("snapshot", data["snapshot"] or "none"),
        KeyValueRow(
            "current set",
            f"{data['current_set'] or 'none'} ({data['current_set_count']})",
        ),
        KeyValueRow("current filing", filing or "none"),
    ]
    if options.include_sets:
        data["sets"] = {name: len(item) for name, item in session.sets.items()}
        rows.extend(
            KeyValueRow(f"set {name}", str(len(item)))
            for name, item in session.sets.items()
        )
    return OpResult(
        kind="key_value",
        title="Session summary",
        components=tuple(rows),
        data=data,
        total=len(data),
        shown=len(data),
        hints=("list operations to discover the next operation",),
    )


_CORE_SPECS: tuple[OperationSpec, ...] = (
    OperationSpec(
        id="session_summary",
        label="Session summary",
        options_type=SessionSummaryOptions,
        effect="reads_state",
        requires="none",
        result_kind="key_value",
        hints=("list operations to discover the next operation",),
        executor=_execute_session_summary,
    ),
)


def assemble_registry(
    *groups: Iterable[OperationSpec],
) -> dict[str, OperationSpec]:
    """Assemble the ordered registry, refusing duplicate operation ids."""
    registry: dict[str, OperationSpec] = {}
    for group in groups:
        for spec in group:
            if spec.id in registry:
                raise ValueError(f"duplicate operation id: {spec.id}")
            registry[spec.id] = spec
    return registry


REGISTRY: dict[str, OperationSpec] = assemble_registry(_CORE_SPECS)


GATHERERS: dict[str, Callable[[ClientSession], Any]] = {}


def _register_sibling_rows() -> None:
    from edgar_sec.apps.client.operator import (
        operator_company,
        operator_config,
        operator_fetch,
        operator_fund,
        operator_run_records,
        operator_selection,
        operator_state,
        operator_tools,
    )

    from edgar_sec.apps.client.operator.drill import (
        operator_drill,
        operator_drill_exhibits,
    )

    operator_selection.register(REGISTRY)
    GATHERERS.update(operator_selection.GATHERERS)
    operator_fetch.register(REGISTRY)
    GATHERERS.update(operator_fetch.GATHERERS)
    operator_run_records.register(REGISTRY)
    GATHERERS.update(operator_run_records.GATHERERS)
    operator_drill.register(REGISTRY)
    GATHERERS.update(operator_drill.GATHERERS)
    operator_drill_exhibits.register(REGISTRY)
    GATHERERS.update(operator_drill_exhibits.GATHERERS)
    operator_tools.register(REGISTRY)
    GATHERERS.update(operator_tools.GATHERERS)
    operator_company.register(REGISTRY)
    GATHERERS.update(operator_company.GATHERERS)
    operator_fund.register(REGISTRY)
    GATHERERS.update(operator_fund.GATHERERS)
    operator_state.register(REGISTRY)
    GATHERERS.update(operator_state.GATHERERS)
    operator_config.register(REGISTRY)
    GATHERERS.update(operator_config.GATHERERS)


_register_sibling_rows()


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
