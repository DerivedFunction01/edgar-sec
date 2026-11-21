"""Pins for the row-spec homes (Wave 2B).
The column factory and row-field lookup live in
``engine.forms.common.row_extraction``; both form packages bind them.
"""

from __future__ import annotations

import pytest

from edgar_sec.engine.forms.common.extraction import FieldKind
from edgar_sec.engine.forms.common.row_extraction import (
    RowSpec,
    column_spec,
    row_field,
)
from edgar_sec.engine.forms.form144 import render_to_xml as form144_render
from edgar_sec.engine.forms.form144 import row_specs as form144_specs
from edgar_sec.engine.forms.ownership import render_to_xml as ownership_render
from edgar_sec.engine.forms.ownership import row_specs as ownership_specs


def test_bindings_are_the_homes() -> None:
    assert form144_specs._column is column_spec
    assert ownership_specs._column is column_spec
    assert form144_render._row_field is row_field
    assert ownership_render._row_field is row_field


def test_column_and_field_verdicts() -> None:
    spec = RowSpec(
        name="sample",
        columns=(column_spec("title", "securityTitle", FieldKind.TEXT),),
    )
    field = row_field(spec, "title")
    assert field.path == "securityTitle"
    assert field.kind is FieldKind.TEXT
    with pytest.raises(KeyError):
        row_field(spec, "missing")


def test_policy_kwargs_pass_through() -> None:
    column = column_spec("amount", "shares", FieldKind.NUMBER, value_child=True)
    assert column.name == "amount"
    assert column.field.value_child is True
