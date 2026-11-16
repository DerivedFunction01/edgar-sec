"""Shared template members for the operator command modules."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import field
from pathlib import Path
from typing import Any

from edgar_sec.foundation.runtime.render import KeyValueRow, ProseRow


def help_field(default: Any, help_text: str):
    """A dataclass field whose help text rides in its metadata."""
    return field(default=default, metadata={"help": help_text})


def key_value_result(
    title: str, data: dict, rows: Iterable[tuple[str, str]], **extra: Any
):
    """A key-value result whose total is its row count."""
    from edgar_sec.apps.client.operator import OpResult

    components = tuple(KeyValueRow(k, v) for k, v in rows)
    return OpResult(
        kind="key_value",
        title=title,
        components=components,
        data=data,
        total=len(components),
        shown=len(components),
        **extra,
    )


def split_tokens(raw: str) -> tuple[str, ...]:
    """Split a comma/space separated operator argument into tokens."""
    return tuple(raw.replace(",", " ").split())


def accession_text(filing: Any) -> str:
    """The accession string of a filing or accession-like value."""
    accession = getattr(filing, "accession", filing)
    return str(getattr(accession, "value", accession))


def make_register(build_specs: Callable[[], Iterable[Any]]) -> Callable[[dict], dict]:
    """Build a module's register function over its own spec builder."""

    def register(registry: dict) -> dict:
        """Add this module's rows to ``registry``, refusing duplicate ids."""
        from edgar_sec.apps.client.operator import assemble_registry

        specs = build_specs()
        assemble_registry(registry.values(), specs)
        for spec in specs:
            registry[spec.id] = spec
        return registry

    return register


def make_module_getattr(
    build_specs: Callable[[], Any], module_name: str
) -> Callable[[str], Any]:
    """Build a module __getattr__ that serves SPECS from its own builder."""

    def __getattr__(name: str):
        if name == "SPECS":
            return build_specs()
        raise AttributeError(f"module {module_name!r} has no attribute {name!r}")

    return __getattr__


def error_result(
    kind: str, code: str, title: str, message: str, data: dict | None = None
):
    """A coded result with the message as its sole prose component."""
    from edgar_sec.apps.client.operator import OpResult

    return OpResult(
        kind=kind,
        title=title,
        components=(ProseRow(message),),
        data={**(data or {}), "message": message},
        error_code=code,
    )


def json_native(value: Any) -> Any:
    """Convert a value tree to JSON-native values, stringifying paths."""
    if isinstance(value, dict):
        return {str(k): json_native(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_native(v) for v in value]
    if isinstance(value, Path):
        return str(value)
    return value


def artifacts_root(session: Any) -> Path:
    """The session's artifacts root, falling back to the resolved paths."""
    root = getattr(session.facade, "artifacts_root", None)
    if root:
        return Path(root)
    from edgar_sec.foundation.runtime.paths import resolve_paths

    return resolve_paths().artifacts_root


def gather_options(session: Any, options_type: type):
    """Gather a module's options through the selection module's gatherer."""
    from edgar_sec.apps.client.operator_selection import _gather_options

    return _gather_options(session, options_type)


def make_spec() -> Callable[..., Any]:
    """Build a module's spec-row closure over the shared row shape."""

    def spec(op_id, label, options_type, effect, kind, executor):
        from edgar_sec.apps.client.operator import OperationSpec

        return OperationSpec(
            id=op_id,
            label=label,
            options_type=options_type,
            effect=effect,
            requires="none",
            result_kind=kind,
            hints=("session_summary",),
            executor=executor,
        )

    return spec


def make_build_specs(rows: Iterable[tuple]) -> Callable[[], tuple]:
    """Build a module's spec builder over its own registry rows."""

    def build_specs() -> tuple:
        """Build the module's registry rows; operator imports resolve at call time."""
        spec = make_spec()

        return tuple(
            spec(op_id, label, options_type, effect, kind, executor)
            for op_id, label, options_type, executor, effect, kind in rows
        )

    return build_specs


__all__ = [
    "accession_text",
    "artifacts_root",
    "error_result",
    "gather_options",
    "help_field",
    "json_native",
    "key_value_result",
    "make_build_specs",
    "make_module_getattr",
    "make_register",
    "make_spec",
    "split_tokens",
]
