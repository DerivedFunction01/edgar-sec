from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from edgar_sec.apps.client.operator.operator_results import OpResult
from edgar_sec.apps.client.operator.operator_session import ClientSession
from edgar_sec.apps.client.operator.operator_specs import OperationSpec
from edgar_sec.foundation.runtime.render import KeyValueRow, RenderComponent

__all__ = [
    "GATHERERS",
    "REGISTRY",
    "assemble_registry",
]


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


# Sibling row modules contribute through a register(registry) function and a
# GATHERERS dict of menu prompt producers, assembled explicitly here.
REGISTRY: dict[str, OperationSpec] = assemble_registry(_CORE_SPECS)


GATHERERS: dict[str, Callable[[ClientSession], Any]] = {}


def _register_sibling_rows() -> None:
    from edgar_sec.apps.client.operator import (
        operator_company,
        operator_config,
        operator_drill,
        operator_drill_exhibits,
        operator_fetch,
        operator_fund,
        operator_run_records,
        operator_selection,
        operator_state,
        operator_tools,
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
