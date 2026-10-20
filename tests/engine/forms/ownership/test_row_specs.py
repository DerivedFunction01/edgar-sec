"""Tests for the declarative ownership table row column specifications."""

from __future__ import annotations

from edgar_sec.domain.forms.families.ownership.taxonomy import (
    OWNERSHIP_ACQUIRED_DISPOSED_CODES,
    OWNERSHIP_STATE_CODES,
    OWNERSHIP_TYPE_CODES,
    VALID_TRANSACTION_CODES,
)
from edgar_sec.domain.taxonomy.jurisdictions import EDGAR_JURISDICTION_CODES
from edgar_sec.engine.forms.common.extraction import FieldKind
from edgar_sec.engine.forms.ownership.row_specs import (
    OWNERSHIP_TABLE_I_ROW_SPEC,
    OWNERSHIP_TABLE_II_ROW_SPEC,
)


def test_table_specs_bind_columns_to_schema_tags() -> None:
    transaction_date = OWNERSHIP_TABLE_I_ROW_SPEC.column("transaction_date")
    assert transaction_date is not None
    assert transaction_date.field.path == "transactionDate"
    assert transaction_date.field.kind is FieldKind.DATE
    assert transaction_date.field.value_child is True


def test_table_specs_cover_the_ownership_model_fields() -> None:
    table_one = {column.name for column in OWNERSHIP_TABLE_I_ROW_SPEC.columns}
    table_two = {column.name for column in OWNERSHIP_TABLE_II_ROW_SPEC.columns}
    assert {"security_title", "transaction_date", "shares_amount"} <= table_one
    assert {
        "conversion_or_exercise_price",
        "exercisable_date",
        "expiration_date",
        "underlying_shares_amount",
    } <= table_two


def test_enum_columns_carry_their_choice_lists() -> None:
    code = OWNERSHIP_TABLE_I_ROW_SPEC.column("transaction_code")
    disposed = OWNERSHIP_TABLE_I_ROW_SPEC.column("acquired_disposed_code")
    nature = OWNERSHIP_TABLE_I_ROW_SPEC.column("direct_or_indirect")
    assert code is not None and disposed is not None and nature is not None
    assert code.field.allowed_values == VALID_TRANSACTION_CODES
    assert disposed.field.allowed_values == OWNERSHIP_ACQUIRED_DISPOSED_CODES
    assert nature.field.allowed_values == OWNERSHIP_TYPE_CODES


def test_ownership_country_set_excludes_ownership_state_codes() -> None:
    country_codes = EDGAR_JURISDICTION_CODES - OWNERSHIP_STATE_CODES
    assert len(EDGAR_JURISDICTION_CODES) == 332
    assert len(OWNERSHIP_STATE_CODES) == 56
    assert len(country_codes) == 278
    assert not country_codes & OWNERSHIP_STATE_CODES
