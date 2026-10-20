"""Declarative ownership table row column specifications."""

from __future__ import annotations

from edgar_sec.domain.forms.families.ownership.taxonomy import (
    OWNERSHIP_ACQUIRED_DISPOSED_CODES,
    OWNERSHIP_TYPE_CODES,
    VALID_TRANSACTION_CODES,
)
from edgar_sec.engine.forms.common.extraction import FieldKind, FieldSpec
from edgar_sec.engine.forms.common.row_extraction import ColumnSpec, RowSpec


def _column(name: str, path: str, kind: FieldKind, **policy: object) -> ColumnSpec:
    return ColumnSpec(name, FieldSpec(path, kind, **policy))


_SHARED_OWNERSHIP_COLUMNS = (
    _column("security_title", "securityTitle", FieldKind.TEXT, value_child=True),
    _column("transaction_date", "transactionDate", FieldKind.DATE, value_child=True),
    _column(
        "transaction_code",
        "transactionCode",
        FieldKind.ENUM,
        allowed_values=VALID_TRANSACTION_CODES,
    ),
    _column("shares_amount", "transactionShares", FieldKind.NUMBER, value_child=True),
    _column(
        "acquired_disposed_code",
        "transactionAcquiredDisposedCode",
        FieldKind.ENUM,
        value_child=True,
        allowed_values=OWNERSHIP_ACQUIRED_DISPOSED_CODES,
    ),
    _column(
        "price_per_share",
        "transactionPricePerShare",
        FieldKind.DECIMAL,
        value_child=True,
    ),
    _column(
        "shares_owned_following",
        "sharesOwnedFollowingTransaction",
        FieldKind.NUMBER,
        value_child=True,
    ),
    _column(
        "direct_or_indirect",
        "directOrIndirectOwnership",
        FieldKind.ENUM,
        value_child=True,
        allowed_values=OWNERSHIP_TYPE_CODES,
    ),
    _column(
        "nature_of_ownership",
        "natureOfOwnership",
        FieldKind.TEXT,
        value_child=True,
    ),
)

OWNERSHIP_TABLE_I_ROW_SPEC = RowSpec(
    name="ownership_table_i",
    columns=_SHARED_OWNERSHIP_COLUMNS,
)

OWNERSHIP_TABLE_II_ROW_SPEC = RowSpec(
    name="ownership_table_ii",
    columns=(
        _column("security_title", "securityTitle", FieldKind.TEXT, value_child=True),
        _column(
            "conversion_or_exercise_price",
            "conversionOrExercisePrice",
            FieldKind.DECIMAL,
            value_child=True,
        ),
        _column(
            "transaction_date", "transactionDate", FieldKind.DATE, value_child=True
        ),
        _column(
            "transaction_code",
            "transactionCode",
            FieldKind.ENUM,
            allowed_values=VALID_TRANSACTION_CODES,
        ),
        _column(
            "shares_amount", "transactionShares", FieldKind.NUMBER, value_child=True
        ),
        _column(
            "acquired_disposed_code",
            "transactionAcquiredDisposedCode",
            FieldKind.ENUM,
            value_child=True,
            allowed_values=OWNERSHIP_ACQUIRED_DISPOSED_CODES,
        ),
        _column("exercisable_date", "exerciseDate", FieldKind.DATE, value_child=True),
        _column("expiration_date", "expirationDate", FieldKind.DATE, value_child=True),
        _column(
            "underlying_security_title",
            "underlyingSecurityTitle",
            FieldKind.TEXT,
            value_child=True,
        ),
        _column(
            "underlying_shares_amount",
            "underlyingSecurityShares",
            FieldKind.NUMBER,
            value_child=True,
        ),
        _column(
            "derivative_shares_owned_following",
            "sharesOwnedFollowingTransaction",
            FieldKind.NUMBER,
            value_child=True,
        ),
        _column(
            "direct_or_indirect",
            "directOrIndirectOwnership",
            FieldKind.ENUM,
            value_child=True,
            allowed_values=OWNERSHIP_TYPE_CODES,
        ),
        _column(
            "nature_of_ownership",
            "natureOfOwnership",
            FieldKind.TEXT,
            value_child=True,
        ),
    ),
)

__all__ = [
    "OWNERSHIP_TABLE_I_ROW_SPEC",
    "OWNERSHIP_TABLE_II_ROW_SPEC",
]
