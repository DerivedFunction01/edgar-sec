from __future__ import annotations

import types
from collections.abc import Mapping
from dataclasses import fields
from pathlib import Path
from typing import Any, Union, get_args, get_origin, get_type_hints

from edgar_sec.apps.client.operator.operator_registry import REGISTRY
from edgar_sec.apps.client.operator.operator_results import OpResult, _error_result
from edgar_sec.apps.client.operator.operator_session import ClientSession
from edgar_sec.apps.client.operator.operator_specs import OperationSpec

__all__ = [
    "decode_options",
    "execute_by_id",
    "execute_operation",
]


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
