"""Registry-generated discovery surfaces: operation listing and per-operation help."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import MISSING, fields, is_dataclass
from typing import Any, get_type_hints

from edgar_sec.foundation.runtime.render import (
    Grid,
    KeyValueRow,
    ProseRow,
    RenderComponent,
)

__all__ = [
    "help_components",
    "listing_components",
    "operation_help",
    "operation_listing",
    "options_schema",
]


def _type_name(annotation: Any) -> str:
    if isinstance(annotation, type):
        return annotation.__name__
    return str(annotation).removeprefix("typing.")


def _json_default(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple, frozenset, set)):
        return [_json_default(item) for item in value]
    return str(value)


def options_schema(options_type: type) -> list[dict[str, Any]]:
    """Describe one options dataclass as JSON-native field rows."""
    if not is_dataclass(options_type):
        return []
    try:
        hints = get_type_hints(options_type)
    except (NameError, TypeError):
        hints = {}
    schema: list[dict[str, Any]] = []
    for item in fields(options_type):
        if item.default is not MISSING:
            default: Any = item.default
            required = False
        elif item.default_factory is not MISSING:
            default = item.default_factory()
            required = False
        else:
            default = None
            required = True
        schema.append(
            {
                "name": item.name,
                "type": _type_name(hints.get(item.name, item.type)),
                "default": _json_default(default),
                "required": required,
                "help": str(item.metadata.get("help", "")),
            }
        )
    return schema


def operation_listing(registry: Mapping[str, Any]) -> dict[str, Any]:
    """Build the listing payload from the registry, never a hand-kept copy."""
    operations = [
        {
            "id": spec.id,
            "label": spec.label,
            "effect": spec.effect,
            "requires": spec.requires,
            "result_kind": spec.result_kind,
            "hints": list(spec.hints),
            "options": options_schema(spec.options_type),
        }
        for spec in registry.values()
    ]
    return {
        "operations": operations,
        "total": len(operations),
        "shown": len(operations),
    }


def listing_components(registry: Mapping[str, Any]) -> tuple[RenderComponent, ...]:
    """Render the listing as an operations grid plus an options-schema grid."""
    payload = operation_listing(registry)
    op_rows = tuple(
        (op["id"], op["label"], op["effect"], op["requires"], op["result_kind"])
        for op in payload["operations"]
    )
    field_rows = tuple(
        (op["id"], field["name"], field["type"], str(field["default"]))
        for op in payload["operations"]
        for field in op["options"]
    )
    return (
        ProseRow(f"Showing {payload['shown']} of {payload['total']} operations"),
        Grid(headers=("id", "label", "effect", "requires", "result"), rows=op_rows),
        Grid(headers=("operation", "field", "type", "default"), rows=field_rows),
    )


def operation_help(spec: Any) -> dict[str, Any]:
    """Build one operation's help payload from its row and options dataclass."""
    return {
        "id": spec.id,
        "label": spec.label,
        "effect": spec.effect,
        "requires": spec.requires,
        "result_kind": spec.result_kind,
        "hints": list(spec.hints),
        "options": options_schema(spec.options_type),
        "invocation": f"--op {spec.id} --options '{{...}}'",
    }


def help_components(spec: Any) -> tuple[RenderComponent, ...]:
    """Render per-operation help; every field line states its default."""
    payload = operation_help(spec)
    rows = tuple(
        (
            field["name"],
            field["type"],
            str(field["default"]),
            field["help"] or f"Selects the {field['name']} value.",
        )
        for field in payload["options"]
    )
    components: list[RenderComponent] = [
        KeyValueRow("operation", f"{payload['id']} — {payload['label']}"),
        KeyValueRow("effect", payload["effect"]),
        KeyValueRow("requires", payload["requires"]),
        KeyValueRow("result", payload["result_kind"]),
        KeyValueRow("invocation", payload["invocation"]),
        Grid(headers=("field", "type", "default", "help"), rows=rows),
    ]
    if payload["hints"]:
        components.append(ProseRow(f"Follow-ups: {', '.join(payload['hints'])}"))
    return tuple(components)
