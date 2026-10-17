"""Tests for form-schema column anchor alignment state machine."""

import pytest

from edgar_sec.engine.forms.common.alignment import (
    CanonicalColumn,
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
