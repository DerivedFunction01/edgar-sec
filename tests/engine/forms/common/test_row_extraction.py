"""Tests for the shared tabular row extraction contract."""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.engine.forms.common.extraction import FieldKind, FieldSpec
from edgar_sec.engine.forms.common.row_extraction import (
    ColumnSpec,
    RowSpec,
    as_integer,
    extract_row,
    normalize_row_record,
    scan_date_cells,
    scan_numeric_cells,
    split_row_cells,
)

_ROW_SPEC = RowSpec(
    name="sample",
    columns=(
        ColumnSpec("title", FieldSpec("securityTitle", FieldKind.TEXT)),
        ColumnSpec("event_date", FieldSpec("eventDate", FieldKind.DATE)),
        ColumnSpec("amount", FieldSpec("amount", FieldKind.NUMBER)),
        ColumnSpec(
            "code",
            FieldSpec("code", FieldKind.ENUM, allowed_values=frozenset({"A", "D"})),
        ),
    ),
)


@dataclass(frozen=True)
class _Row:
    title: str | None = None
    event_date: str | None = None
    amount: str | None = None
    code: str | None = None


def test_extract_row_canonicalizes_dates_and_numbers() -> None:
    extraction = extract_row(
        {
            "title": " Common Stock ",
            "event_date": "05/15/2024",
            "amount": "1,234.000",
            "code": "A",
        },
        _ROW_SPEC,
        reference_year=2024,
    )
    assert extraction.values["title"] == "Common Stock"
    assert extraction.values["event_date"] == "2024-05-15"
    assert extraction.values["amount"] == "1234"
    assert extraction.values["code"] == "A"
    assert extraction.evidence() == ()


def test_extract_row_retains_raw_for_unresolvable_values() -> None:
    extraction = extract_row(
        {"event_date": "05/15/24", "amount": "-500"},
        _ROW_SPEC,
    )
    assert extraction.values["event_date"] == "05/15/24"
    assert extraction.values["amount"] == "-500"
    roles = {str(record["role"]) for record in extraction.evidence()}
    assert roles == {
        "normalization.unresolved:eventDate",
        "normalization.unresolved:amount",
    }


def test_extract_row_records_constraint_violations_without_dropping_values() -> None:
    extraction = extract_row({"code": "Z"}, _ROW_SPEC)
    assert extraction.values["code"] == "Z"
    records = extraction.evidence()
    assert len(records) == 1
    assert records[0]["role"] == "normalization.unresolved:code"
    assert records[0]["normalization_status"] == "choice"


def test_normalize_row_record_updates_matching_fields() -> None:
    normalized, extraction = normalize_row_record(
        _Row(
            title=" Common Stock ",
            event_date="05/15/2024",
            amount="10",
            code="A",
        ),
        _ROW_SPEC,
        reference_year=2024,
    )
    assert normalized.event_date == "2024-05-15"
    assert normalized.amount == "10"
    assert extraction.results


def test_split_row_cells_expands_pipe_delimited_cells() -> None:
    assert split_row_cells(["a|b", " c ", "", "d"]) == ("a", "b", "c", "d")


def test_scan_date_cells_reports_index_and_text() -> None:
    assert scan_date_cells(["plain", "05/15/2024", "x"]) == ((1, "05/15/2024"),)


def test_scan_numeric_cells_skips_currency_unless_requested() -> None:
    cells = ("1,000", "$2,000", "text")
    assert scan_numeric_cells(cells) == ((0, "1,000"),)
    assert scan_numeric_cells(cells, currency=True) == (
        (0, "1,000"),
        (1, "$2,000"),
    )


def test_scan_numeric_cells_honors_exclusions_and_denied_markers() -> None:
    cells = ("1,000", "2,000", "1/2")
    assert scan_numeric_cells(cells, excluded=frozenset({0, 2})) == ((1, "2,000"),)
    assert scan_numeric_cells(cells, deny=("/",)) == ((0, "1,000"), (1, "2,000"))


def test_as_integer_keeps_raw_text_for_non_integral_values() -> None:
    assert as_integer("10000") == 10000
    assert as_integer(10000) == 10000
    assert as_integer("abc") == "abc"
    assert as_integer(None) is None
