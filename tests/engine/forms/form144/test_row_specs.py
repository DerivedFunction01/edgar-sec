"""Tests for the declarative Form 144 table row column specifications."""

from __future__ import annotations

from edgar_sec.engine.forms.common.extraction import FieldKind
from edgar_sec.engine.forms.form144.row_specs import (
    FORM144_PROPOSED_SALE_ROW_SPEC,
    FORM144_TABLE_I_ROW_SPEC,
    FORM144_TABLE_II_ROW_SPEC,
)


def test_table_specs_bind_columns_to_schema_tags() -> None:
    acquired = FORM144_TABLE_I_ROW_SPEC.column("acquired_date")
    assert acquired is not None
    assert acquired.field.path == "acquiredDate"
    assert acquired.field.kind is FieldKind.DATE
    assert acquired.field.date_lexeme == "MDY"


def test_table_specs_cover_the_form144_model_fields() -> None:
    table_one = {column.name for column in FORM144_TABLE_I_ROW_SPEC.columns}
    table_two = {column.name for column in FORM144_TABLE_II_ROW_SPEC.columns}
    proposed = {column.name for column in FORM144_PROPOSED_SALE_ROW_SPEC.columns}
    assert {"class_title", "acquired_date", "amount_acquired"} <= table_one
    assert {"seller_name", "sale_date", "gross_proceeds"} <= table_two
    assert {"units_to_be_sold", "aggregate_market_value"} <= proposed


def test_numeric_columns_declare_their_normalization_policy() -> None:
    acquired = FORM144_TABLE_I_ROW_SPEC.column("amount_acquired")
    proceeds = FORM144_TABLE_II_ROW_SPEC.column("gross_proceeds")
    market_value = FORM144_PROPOSED_SALE_ROW_SPEC.column("aggregate_market_value")
    assert acquired is not None and proceeds is not None and market_value is not None
    assert acquired.field.kind is FieldKind.INTEGER
    assert acquired.field.strip_units is True
    assert proceeds.field.kind is FieldKind.DECIMAL
    assert proceeds.field.strip_currency is True
    assert market_value.field.allow_accounting_negative is True
