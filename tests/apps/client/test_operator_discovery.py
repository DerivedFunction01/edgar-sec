"""Tests for the operator's generated listing and help surfaces."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from edgar_sec.apps.client import operator
from edgar_sec.apps.client.operator_discovery import (
    help_components,
    listing_components,
    operation_help,
    operation_listing,
    options_schema,
)
from edgar_sec.foundation.runtime.render import Grid, KeyValueRow


@dataclass(frozen=True)
class _Options:
    limit: int = field(
        default=5, metadata={"help": "Selects the row cap. Refused below 1."}
    )
    forms: tuple[str, ...] = ("10-K",)


def _spec():
    return operator.OperationSpec(
        id="probe",
        label="Probe",
        options_type=_Options,
        effect="reads_state",
        requires="none",
        result_kind="prose",
        executor=lambda options, session: operator.OpResult(kind="prose"),
    )


def test_options_schema_names_types_defaults() -> None:
    schema = options_schema(_Options)
    assert schema[0]["name"] == "limit"
    assert schema[0]["type"] == "int"
    assert schema[0]["default"] == 5
    assert schema[0]["help"]
    assert schema[1]["default"] == ["10-K"]
    assert json.dumps(schema)


def test_listing_includes_schema_and_renders() -> None:
    registry = {"probe": _spec()}
    payload = operation_listing(registry)
    assert payload["operations"][0]["options"][0]["name"] == "limit"
    components = listing_components(registry)
    grids = [item for item in components if isinstance(item, Grid)]
    assert grids[0].rows[0][0] == "probe"
    assert grids[1].rows[0][1] == "limit"


def test_help_states_default_and_refusal() -> None:
    payload = operation_help(_spec())
    assert payload["options"][0]["default"] == 5
    assert payload["invocation"] == "--op probe --options '{...}'"
    rows = [
        (item.label, item.value)
        for item in help_components(_spec())
        if isinstance(item, KeyValueRow)
    ]
    assert ("invocation", "--op probe --options '{...}'") in rows
    text = "\n".join(
        cell
        for item in help_components(_spec())
        if isinstance(item, Grid)
        for row in item.rows
        for cell in row
    )
    assert "Refused below 1" in text
    assert "5" in text
