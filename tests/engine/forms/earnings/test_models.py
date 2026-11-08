"""Tests for the earnings result records."""

from edgar_sec.engine.forms.earnings.models import (
    EarningsExhibitResult,
    EarningsTable,
    EarningsTableRow,
    ExhibitCandidate,
    ReviewSignal,
)


def test_result_records_are_frozen_tuples() -> None:
    """Result records carry tuples and an optional absence reason."""
    table = EarningsTable(
        table_index=0,
        caption=None,
        periods=("2024",),
        rows=(EarningsTableRow(label="Revenue", values=("100",)),),
        roles=("income_statement",),
    )
    result = EarningsExhibitResult(
        accession="0000000000-00-000001",
        form="8-K",
        exhibit=ExhibitCandidate(
            filename="ex99-1.htm",
            document_type="EX-99.1",
            exhibit_number=1,
            family="modern",
            kind="html",
        ),
        tables=(table,),
        headline=None,
        review_signals=(
            ReviewSignal(kind="k", specimen_class="c", filename="ex99-1.htm"),
        ),
        text="",
    )
    assert result.tables[0].rows[0].values == ("100",)
    assert result.absence_reason is None
    assert result.review_signals[0].table_index is None
