"""Declarative Form 144 table row column specifications."""

from __future__ import annotations

from edgar_sec.engine.forms.common.extraction import FieldKind, FieldSpec
from edgar_sec.engine.forms.common.row_extraction import ColumnSpec, RowSpec


def _column(name: str, path: str, kind: FieldKind, **policy: object) -> ColumnSpec:
    return ColumnSpec(name, FieldSpec(path, kind, **policy))


FORM144_TABLE_I_ROW_SPEC = RowSpec(
    name="form144_table_i",
    columns=(
        _column("class_title", "securitiesClassTitle", FieldKind.TEXT),
        _column("acquired_date", "acquiredDate", FieldKind.DATE, date_lexeme="MDY"),
        _column(
            "nature_of_acquisition",
            "natureOfAcquisitionTransaction",
            FieldKind.TEXT,
        ),
        _column(
            "donor_or_seller_name",
            "nameOfPersonfromWhomAcquired",
            FieldKind.TEXT,
        ),
        _column(
            "amount_acquired",
            "amountOfSecuritiesAcquired",
            FieldKind.INTEGER,
            strip_units=True,
            allow_integral_decimal=True,
        ),
        _column("payment_date", "paymentDate", FieldKind.DATE, date_lexeme="MDY"),
        _column("nature_of_payment", "natureOfPayment", FieldKind.TEXT),
    ),
)

FORM144_TABLE_II_ROW_SPEC = RowSpec(
    name="form144_table_ii",
    columns=(
        _column("seller_name", "name", FieldKind.TEXT),
        _column("class_title", "securitiesClassTitle", FieldKind.TEXT),
        _column("sale_date", "saleDate", FieldKind.DATE, date_lexeme="MDY"),
        _column(
            "amount_sold",
            "amountOfSecuritiesSold",
            FieldKind.INTEGER,
            strip_units=True,
            allow_integral_decimal=True,
        ),
        _column(
            "gross_proceeds",
            "grossProceeds",
            FieldKind.DECIMAL,
            strip_currency=True,
            allow_accounting_negative=True,
            allow_negative=True,
        ),
    ),
)

FORM144_PROPOSED_SALE_ROW_SPEC = RowSpec(
    name="form144_proposed_sale",
    columns=(
        _column("class_title", "securitiesClassTitle", FieldKind.TEXT),
        _column(
            "units_to_be_sold",
            "noOfUnitsSold",
            FieldKind.INTEGER,
            strip_units=True,
            allow_integral_decimal=True,
        ),
        _column(
            "aggregate_market_value",
            "aggregateMarketValue",
            FieldKind.DECIMAL,
            strip_currency=True,
            allow_accounting_negative=True,
            allow_negative=True,
        ),
        _column(
            "units_outstanding",
            "noOfUnitsOutstanding",
            FieldKind.INTEGER,
            strip_units=True,
            allow_integral_decimal=True,
        ),
        _column(
            "approx_sale_date", "approxSaleDate", FieldKind.DATE, date_lexeme="MDY"
        ),
        _column("exchange_name", "securitiesExchangeName", FieldKind.TEXT),
    ),
)

__all__ = [
    "FORM144_PROPOSED_SALE_ROW_SPEC",
    "FORM144_TABLE_I_ROW_SPEC",
    "FORM144_TABLE_II_ROW_SPEC",
]
