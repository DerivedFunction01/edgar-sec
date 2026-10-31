"""Tests for form-schema column anchor alignment state machine."""

import pytest

from edgar_sec.engine.forms.common.alignment import (
    CanonicalColumn,
    SourceCell,
    TableSchema,
    align_row_to_schema,
    find_strict_anchors,
)


@pytest.fixture
def sample_schema() -> TableSchema:
    return TableSchema(
        name="test_schema",
        columns=(
            CanonicalColumn(index=0, name="title", is_required=True),
            CanonicalColumn(
                index=1,
                name="date",
                is_required=True,
                is_anchor=True,
                anchor_validator=lambda s: "/" in s and len(s) >= 8,
            ),
            CanonicalColumn(index=2, name="deemed_date", is_required=False),
            CanonicalColumn(
                index=3,
                name="code",
                is_required=True,
                is_anchor=True,
                anchor_validator=lambda s: s in {"P", "S", "A", "D", "M"},
            ),
            CanonicalColumn(
                index=4,
                name="shares",
                is_required=True,
                data_extractor=lambda s: float(s.replace(",", "")),
            ),
            CanonicalColumn(
                index=5,
                name="form",
                is_required=True,
                is_anchor=True,
                anchor_validator=lambda s: s in {"D", "I"},
            ),
            CanonicalColumn(index=6, name="nature", is_required=False),
        ),
    )


def test_align_full_row(sample_schema: TableSchema) -> None:
    """Verify alignment when every canonical column is present in the raw cells."""
    cells = ("Common Stock", "04/01/1999", "04/02/1999", "P", "1,000", "D", "Direct")
    res = align_row_to_schema(cells, sample_schema)
    assert res is not None
    assert res["title"] == "Common Stock"
    assert res["date"] == "04/01/1999"
    assert res["deemed_date"] == "04/02/1999"
    assert res["code"] == "P"
    assert res["shares"] == 1000.0
    assert res["form"] == "D"
    assert res["nature"] == "Direct"


def test_align_missing_optional_column(sample_schema: TableSchema) -> None:
    """Verify deficit logic assigns None to unpopulated optional columns."""
    cells = ("Common Stock", "04/01/1999", "P", "1,000", "D")
    res = align_row_to_schema(cells, sample_schema)
    assert res is not None
    assert res["title"] == "Common Stock"
    assert res["date"] == "04/01/1999"
    assert res["deemed_date"] is None
    assert res["code"] == "P"
    assert res["shares"] == 1000.0
    assert res["form"] == "D"
    assert res["nature"] is None


def test_align_rejects_missing_required_column(sample_schema: TableSchema) -> None:
    """Reject rows that lack cells to satisfy all required canonical columns."""
    cells = ("Common Stock", "04/01/1999", "P")
    res = align_row_to_schema(cells, sample_schema)
    assert res is None


def test_find_strict_anchors_monotonicity(sample_schema: TableSchema) -> None:
    """Ensure strict anchor matcher preserves monotonic forward progression."""
    cells = ("Common Stock", "04/01/1999", "P", "500", "D")
    anchors = find_strict_anchors(cells, sample_schema)
    assert len(anchors) == 3
    assert [a.col_index for a in anchors] == [1, 3, 5]
    assert [a.cell_index for a in anchors] == [1, 2, 4]


def test_align_source_cells_keeps_an_empty_column_at_its_position() -> None:
    schema = TableSchema(
        name="positioned_schema",
        columns=(
            CanonicalColumn(
                index=0,
                name="title",
                is_required=True,
                is_anchor=True,
                anchor_validator=lambda value: value == "Common Stock",
            ),
            CanonicalColumn(
                index=1,
                name="ownership_form",
                is_required=True,
                is_anchor=True,
                anchor_validator=lambda value: value in {"D", "I"},
            ),
            CanonicalColumn(index=2, name="nature", is_required=False),
        ),
    )

    result = align_row_to_schema(
        (
            SourceCell(0, 0, "Common Stock"),
            SourceCell(1, 0, ""),
            SourceCell(2, 0, "By spouse"),
        ),
        schema,
    )

    assert result == {
        "title": "Common Stock",
        "ownership_form": None,
        "nature": "By spouse",
    }


def test_aligned_source_cells_preserve_invalid_values_without_shifting() -> None:
    schema = TableSchema(
        name="positioned_schema",
        columns=(
            CanonicalColumn(
                index=0,
                name="title",
                is_required=True,
                is_anchor=True,
                anchor_validator=lambda value: value == "Common Stock",
            ),
            CanonicalColumn(
                index=1,
                name="ownership_form",
                is_required=False,
                is_anchor=True,
                anchor_validator=lambda value: value in {"D", "I"},
                value_validator=lambda value: value in {"D", "I"},
                preserve_invalid_exact_value=True,
            ),
            CanonicalColumn(
                index=2,
                name="nature",
                is_required=False,
                is_anchor=True,
                anchor_validator=lambda value: value == "D",
            ),
        ),
    )

    result = align_row_to_schema(
        (
            SourceCell(0, 0, "Common Stock"),
            SourceCell(1, 0, "By spouse"),
            SourceCell(2, 0, "D"),
        ),
        schema,
    )

    assert result == {
        "title": "Common Stock",
        "ownership_form": "By spouse",
        "nature": "D",
    }


def test_invalid_exact_values_are_rejected_without_opt_in() -> None:
    schema = TableSchema(
        name="positioned_schema",
        columns=(
            CanonicalColumn(
                index=0,
                name="title",
                is_anchor=True,
                anchor_validator=lambda value: bool(value),
            ),
            CanonicalColumn(
                index=1,
                name="date",
                is_anchor=True,
                anchor_validator=lambda value: value.isdigit(),
                value_validator=lambda value: value.isdigit(),
            ),
        ),
    )

    result = align_row_to_schema(
        (SourceCell(0, 0, "Common Stock"), SourceCell(1, 0, "Immediately")),
        schema,
    )

    assert result is None


def test_source_cells_with_non_schema_width_use_compacted_anchor_alignment() -> None:
    schema = TableSchema(
        name="positioned_schema",
        columns=(
            CanonicalColumn(index=0, name="title", is_required=True),
            CanonicalColumn(
                index=1,
                name="transaction_code",
                is_anchor=True,
                anchor_validator=lambda value: value in {"P", "S"},
            ),
            CanonicalColumn(
                index=2,
                name="shares",
                data_extractor=lambda value: value,
                value_validator=lambda value: value.isdigit(),
            ),
        ),
    )
    source_cells = (
        SourceCell(0, 0, "Common Stock"),
        SourceCell(1, 0, ""),
        SourceCell(2, 0, "P"),
        SourceCell(3, 0, "100"),
    )

    assert align_row_to_schema(source_cells, schema) == align_row_to_schema(
        ("Common Stock", "P", "100"), schema
    )


def test_value_contract_eliminates_an_assignment() -> None:
    """A value that breaks its column contract cannot fill that column."""
    schema = TableSchema(
        name="nonnegative_schema",
        columns=(
            CanonicalColumn(index=0, name="title", is_required=True),
            CanonicalColumn(
                index=1,
                name="shares",
                is_required=False,
                data_extractor=lambda s: s,
                value_validator=lambda s: not s.startswith("-"),
            ),
            CanonicalColumn(
                index=2,
                name="price",
                is_required=False,
                data_extractor=lambda s: s,
                value_validator=lambda s: not s.startswith("-"),
            ),
        ),
    )

    res = align_row_to_schema(("Common Stock", "-500", "12.00"), schema)

    assert res is not None
    assert res["title"] == "Common Stock"
    assert res["price"] == "12.00"
    assert res["shares"] == "-500"


def test_value_contract_keeps_the_only_reading_when_no_other_column_fits() -> None:
    """A rejected value stays put when no later column can hold it."""
    schema = TableSchema(
        name="single_amount_schema",
        columns=(
            CanonicalColumn(index=0, name="title", is_required=True),
            CanonicalColumn(
                index=1,
                name="shares",
                is_required=False,
                data_extractor=lambda s: s,
                value_validator=lambda s: not s.startswith("-"),
            ),
        ),
    )

    res = align_row_to_schema(("Common Stock", "-500"), schema)

    assert res is not None
    assert res["shares"] == "-500"
