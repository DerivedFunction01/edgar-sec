from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, is_dataclass
from typing import Any

from edgar_sec.apps.client.operator.operator_results import RESULT_KINDS, OpResult
from edgar_sec.apps.client.operator.operator_session import ClientSession

__all__ = [
    "EFFECTS",
    "REQUIREMENTS",
    "Executor",
    "OperationSpec",
]


EFFECTS = frozenset(
    {"reads_state", "mutates_selection", "moves_position", "external", "destructive"}
)


REQUIREMENTS = frozenset({"none", "selection", "current_filing", "snapshot_context"})


Executor = Callable[[Any, ClientSession], OpResult]


@dataclass(frozen=True, slots=True)
class OperationSpec:
    """One registry row: typed options, closed vocabularies, one executor."""

    id: str
    label: str
    options_type: type
    effect: str
    requires: str
    result_kind: str
    hints: tuple[str, ...] = ()
    executor: Executor | None = None
    available: Callable[[ClientSession], bool] | None = None

    def __post_init__(self) -> None:
        if self.effect not in EFFECTS:
            raise ValueError(f"unknown effect: {self.effect!r}")
        if self.requires not in REQUIREMENTS:
            raise ValueError(f"unknown requirement: {self.requires!r}")
        if self.result_kind not in RESULT_KINDS:
            raise ValueError(f"unknown result kind: {self.result_kind!r}")
        if not is_dataclass(self.options_type):
            raise ValueError(f"options_type is not a dataclass: {self.options_type!r}")
        if not callable(self.executor):
            raise ValueError(f"executor is not callable for operation {self.id!r}")
