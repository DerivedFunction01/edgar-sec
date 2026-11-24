"""Client operator execution core: vocabularies, specs, results, dispatch."""

from __future__ import annotations

import types
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any, Union, get_args, get_origin, get_type_hints

from edgar_sec.apps.client.operator.operator_session import ClientSession
from edgar_sec.foundation.runtime.render import ProseRow, RenderComponent

__all__ = [
    "EFFECTS",
    "ERROR_CODES",
    "REQUIREMENTS",
    "RESULT_KINDS",
    "OpResult",
    "OperationSpec",
    "decode_options",
    "execute_by_id",
    "execute_operation",
]


EFFECTS = frozenset(
    {"reads_state", "mutates_selection", "moves_position", "external", "destructive"}
)


REQUIREMENTS = frozenset({"none", "selection", "current_filing", "snapshot_context"})


RESULT_KINDS = frozenset({"grid", "key_value", "prose", "object"})


ERROR_CODES = frozenset(
    {
        "invalid_options",
        "missing_context",
        "unknown_operation",
        "refused",
        "not_found",
        "absent",
        "external_failure",
        "unsupported_version",
    }
)


@dataclass(frozen=True, slots=True)
class OpResult:
    """One operation outcome; ``total``/``shown`` declare the clamp, if any."""

    kind: str
    title: str = ""
    components: tuple[RenderComponent, ...] = ()
    data: dict[str, Any] = field(default_factory=dict)
    total: int = 0
    shown: int = 0
    error_code: str | None = None
    hints: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.kind not in RESULT_KINDS:
            raise ValueError(f"unknown result kind: {self.kind!r}")
        if self.error_code is not None and self.error_code not in ERROR_CODES:
            raise ValueError(f"unknown error code: {self.error_code!r}")
        if self.total < 0 or self.shown < 0 or self.shown > self.total:
            raise ValueError("shown must lie between 0 and total")

    def to_payload(self) -> dict[str, Any]:
        """The JSON-native rendering every operation offers."""
        message: str | None = None
        if self.error_code is not None:
            prose = next(
                (row.text for row in self.components if isinstance(row, ProseRow)),
                None,
            )
            carried = self.data.get("message")
            message = (
                prose if prose is not None else (str(carried) if carried else None)
            )
        return {
            "kind": self.kind,
            "title": self.title,
            "data": self.data,
            "total": self.total,
            "shown": self.shown,
            "error_code": self.error_code,
            "message": message,
            "hints": list(self.hints),
        }


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


def _error_result(
    kind: str, code: str, title: str, message: str, data: dict[str, Any] | None = None
) -> OpResult:
    return OpResult(
        kind=kind,
        title=title,
        components=(ProseRow(message),) if message else (),
        data=data or {},
        error_code=code,
    )


def _coerce(value: Any, annotation: Any) -> Any:
    origin = get_origin(annotation)
    args = get_args(annotation)
    if annotation is Any or annotation is None:
        return value
    if origin is Union or isinstance(annotation, types.UnionType):
        if value is None and type(None) in args:
            return None
        for candidate in args:
            if candidate is type(None):
                continue
            try:
                return _coerce(value, candidate)
            except (TypeError, ValueError):
                continue
        raise ValueError(f"cannot coerce {value!r} to {annotation}")
    if annotation is bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.lower() in {"true", "yes", "1"}:
            return True
        if isinstance(value, str) and value.lower() in {"false", "no", "0"}:
            return False
        raise ValueError(f"cannot coerce {value!r} to bool")
    if annotation is int:
        if isinstance(value, bool):
            raise ValueError(f"cannot coerce {value!r} to int")
        return int(value)
    if annotation is float:
        if isinstance(value, bool):
            raise ValueError(f"cannot coerce {value!r} to float")
        return float(value)
    if annotation is str:
        if not isinstance(value, str):
            raise ValueError(f"cannot coerce {value!r} to str")
        return value
    if annotation is Path:
        return Path(str(value))
    if origin in (tuple, list, frozenset, set) or annotation in (
        tuple,
        list,
        frozenset,
        set,
    ):
        if not isinstance(value, (list, tuple)):
            raise ValueError(f"cannot coerce {value!r} to a sequence")
        element = args[0] if args and args[0] is not Ellipsis else Any
        items = [_coerce(item, element) for item in value]
        container = origin or annotation
        return container(items)
    if isinstance(annotation, type) and isinstance(value, annotation):
        return value
    if isinstance(annotation, type):
        return annotation(value)
    return value


def decode_options(spec: OperationSpec, raw: Mapping[str, Any] | None) -> Any:
    """Decode a JSON-native mapping into the row's options dataclass."""
    values = dict(raw or {})
    hints = get_type_hints(spec.options_type)
    known = {item.name for item in fields(spec.options_type)}
    unknown = sorted(set(values) - known)
    if unknown:
        raise ValueError(f"unknown option field(s): {', '.join(unknown)}")
    kwargs: dict[str, Any] = {}
    for item in fields(spec.options_type):
        if item.name in values:
            kwargs[item.name] = _coerce(
                values[item.name], hints.get(item.name, item.type)
            )
    try:
        return spec.options_type(**kwargs)
    except (TypeError, ValueError) as exc:
        raise ValueError(str(exc)) from exc


def execute_operation(
    spec: OperationSpec, session: ClientSession, options: Any = None
) -> OpResult:
    """Execute one row, mapping every failure onto the closed error vocabulary."""
    if options is None:
        try:
            options = spec.options_type()
        except (TypeError, ValueError) as exc:
            return _error_result(
                spec.result_kind, "invalid_options", spec.label, str(exc)
            )
    if not isinstance(options, spec.options_type):
        return _error_result(
            spec.result_kind,
            "invalid_options",
            spec.label,
            f"options must be {spec.options_type.__name__}",
        )
    if not session.satisfies(spec.requires):
        return _error_result(
            spec.result_kind,
            "missing_context",
            spec.label,
            f"operation requires {spec.requires}",
            {"requires": spec.requires},
        )
    try:
        result = spec.executor(options, session)
    except Exception as exc:  # noqa: BLE001 - executor failures become coded results
        return _error_result(spec.result_kind, "external_failure", spec.label, str(exc))
    if not isinstance(result, OpResult) or result.kind != spec.result_kind:
        return _error_result(
            spec.result_kind,
            "external_failure",
            spec.label,
            "executor returned a result of the wrong kind",
        )
    return result


def execute_by_id(
    op_id: str,
    session: ClientSession,
    raw_options: Mapping[str, Any] | None = None,
    registry: Mapping[str, OperationSpec] | None = None,
) -> OpResult:
    """Resolve, decode, and execute one operation by registry id."""
    from edgar_sec.apps.client.operator.operator import REGISTRY

    specs = REGISTRY if registry is None else registry
    spec = specs.get(op_id)
    if spec is None:
        return _error_result(
            "object",
            "unknown_operation",
            op_id,
            f"unknown operation: {op_id}",
            {"operation": op_id},
        )
    try:
        options = decode_options(spec, raw_options)
    except ValueError as exc:
        return _error_result(spec.result_kind, "invalid_options", spec.label, str(exc))
    return execute_operation(spec, session, options)
