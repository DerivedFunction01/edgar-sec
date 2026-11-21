"""TOC gate: span tables refused on the fact, later ones on content."""

from __future__ import annotations

from edgar_sec.engine.tables.ascii_html.model.model import (
    ResolvedGrid,
    TableGeometry,
    TableRenderResult,
)
from edgar_sec.engine.tables.extraction.cascade.scoring.classify import (
    classify_filing,
    classify_table,
)
from edgar_sec.engine.tables.extraction.core.text.context import TableContext
from edgar_sec.engine.tables.extraction.seats.toc_gate import toc_refusal, toc_signals
from edgar_sec.engine.tables.extraction.core.typed_rows import (
    CaptionInfo,
    ColumnPeriod,
    RowKind,
    TypedRow,
    TypedTable,
)

_COVER_TOC = (
    ("PART I", ()),
    ("Item 1. Business", (1.0,)),
    ("Item 1A. Risk Factors", (4.0,)),
    ("Item 2. Properties", (9.0,)),
    ("Item 3. Legal Proceedings", (9.0,)),
    ("Item 7. Management's Discussion and Analysis", (12.0,)),
    ("Item 8. Financial Statements and Supplementary Data", (26.0,)),
)

_NOTE_INDEX = (
    ("Fair value measurement", (159.0,)),
    ("Derivative instruments", (184.0,)),
    ("Pension and other postretirement benefit plans", (202.0,)),
    ("Employee share-based incentives", (209.0,)),
    ("Goodwill and other intangible assets", (252.0,)),
    ("Premises and equipment", (256.0,)),
    ("Long-term debt", (261.0,)),
)

_STATEMENT_INDEX = (
    ("Condensed Consolidated Balance Sheets", (3.0,)),
    ("Condensed Consolidated Statements of Operations", (4.0,)),
    ("Condensed Consolidated Statements of Comprehensive Income", (6.0,)),
    ("Condensed Consolidated Statements of Cash Flows", (7.0,)),
    ("Condensed Consolidated Statements of Stockholders' Equity", (8.0,)),
    ("Notes to Condensed Consolidated Financial Statements", (9.0,)),
)

_BALANCE_SHEET = (
    ("Cash and cash equivalents", (1234.0,)),
    ("Accounts receivable, net", (567.0,)),
    ("Total current assets", (1801.0,)),
    ("Property and equipment, net", (890.0,)),
    ("Total assets", (2691.0,)),
    ("Accounts payable", (345.0,)),
    ("Total current liabilities", (345.0,)),
    ("Total liabilities and stockholders' equity", (2691.0,)),
)


def _raw(label: str, values: tuple[float, ...]) -> tuple[str, ...]:
    if label in ("Fair value measurement", "Derivative instruments"):
        note = "Note 2" if label.startswith("Fair") else "Note 5"
        return (label, note, f"Page {int(values[0])}")
    if label.startswith(("Item", "PART")):
        return (label, str(int(values[0])) if values else "")
    if label in _BALANCE_SHEET_LABELS or (values and values[0] >= 1000):
        return (label, "$", f"{int(values[0]):,}")
    return (label, str(int(values[0])) if values else "")


_BALANCE_SHEET_LABELS = {label for label, _ in _BALANCE_SHEET}


def _table(
    rows: tuple[tuple[str, tuple[float, ...]], ...],
    *,
    index: int = 0,
    in_span: bool = False,
) -> TypedTable:
    geometry = TableGeometry(
        table_index=index,
        render_result=TableRenderResult(
            ascii_text="",
            resolved_grid=ResolvedGrid(
                rows=(), column_alignments=(), column_widths=(), header_row_count=0
            ),
            confidence=1.0,
        ),
    )
    context = TableContext(geometry=geometry, in_toc_span=in_span)
    typed = tuple(
        TypedRow(label=label, values=values, kind=RowKind.DATA, raw=_raw(label, values))
        for label, values in rows
    )
    return TypedTable(
        context=context,
        caption=CaptionInfo(
            lines=(),
            company=None,
            titles=(),
            audit_status=None,
            scale=None,
            continued=False,
            consumed_rows=0,
        ),
        periods=(ColumnPeriod(1, None, "2024", "2024"),),
        rows=typed,
        scale=None,
        header_rows=0,
        continued=False,
    )


def _raw_table(specimens: tuple[tuple[str, tuple[str, ...]], ...]) -> TypedTable:
    geometry = TableGeometry(
        table_index=0,
        render_result=TableRenderResult(
            ascii_text="",
            resolved_grid=ResolvedGrid(
                rows=(), column_alignments=(), column_widths=(), header_row_count=0
            ),
            confidence=1.0,
        ),
    )
    context = TableContext(geometry=geometry, in_toc_span=False)
    typed = tuple(
        TypedRow(label=label, values=(), kind=RowKind.DATA, raw=raw)
        for label, raw in specimens
    )
    return TypedTable(
        context=context,
        caption=CaptionInfo(
            lines=(),
            company=None,
            titles=(),
            audit_status=None,
            scale=None,
            continued=False,
            consumed_rows=0,
        ),
        periods=(ColumnPeriod(1, None, "2024", "2024"),),
        rows=typed,
        scale=None,
        header_rows=0,
        continued=False,
    )


def test_table_inside_cover_span_is_refused_on_the_fact() -> None:
    table = _table(_COVER_TOC, index=6, in_span=True)
    result = classify_table(table)
    assert result.family == "other"
    assert result.tier == "genre_refusal"
    assert any(
        entry.group == "genre_refusal" and "toc refused (cover span)" in entry.detail
        for entry in result.evidence
    )


def test_span_fact_refuses_even_an_unshaped_table() -> None:
    table = _table(_BALANCE_SHEET, index=3, in_span=True)
    assert not toc_signals(table).shaped
    refusal = toc_refusal(table)
    assert refusal is not None
    assert "toc refused (cover span)" in refusal.detail


def test_position_alone_no_longer_refuses() -> None:
    table = _table(_COVER_TOC, index=2)
    assert toc_signals(table).shaped
    assert toc_refusal(table) is None


def test_note_index_later_is_refused_on_content() -> None:
    table = _table(_NOTE_INDEX, index=224)
    signals = toc_signals(table)
    assert signals.shaped
    assert not signals.currency_present
    assert len(signals.families) >= 4
    result = classify_table(table)
    assert result.tier == "genre_refusal"
    assert any("toc refused (content)" in entry.detail for entry in result.evidence)


def test_statement_index_later_is_refused_on_content() -> None:
    table = _table(_STATEMENT_INDEX, index=40)
    assert toc_refusal(table) is not None
    assert classify_table(table).tier == "genre_refusal"


def test_money_carrying_index_later_is_not_refused() -> None:
    rows = tuple((label, values) for label, values in _NOTE_INDEX[:6]) + (
        ("Long-term debt", (1234.0,)),
    )
    table = _table(rows, index=224)
    assert toc_signals(table).currency_present
    assert toc_refusal(table) is None


def test_balance_sheet_with_amounts_is_not_toc_shaped() -> None:
    table = _table(_BALANCE_SHEET, index=20)
    assert toc_refusal(table) is None
    assert classify_table(table).family == "balance_sheet"


def test_constant_value_rows_are_not_page_references() -> None:
    labels = (
        "Revenue from contracts with customers",
        "Cost of goods sold",
        "Gross margin",
        "Selling and administrative expenses",
        "Operating income",
        "Net income",
    )
    rows = tuple((label, (1.0,)) for label in labels)
    table = _table(rows, index=2)
    assert not toc_signals(table).shaped
    assert toc_refusal(table) is None


def test_labelled_page_reference_shapes_are_strong() -> None:
    # Two-consumer specimen set, detection side: every labelled shape the
    # homed RE_PAGE_REFERENCE recognizes is a strong page reference.
    table = _raw_table(
        (
            ("Item 1. Business", ("Item 1. Business", "Page 12")),
            ("Item 2. Properties", ("Item 2. Properties", "Page No. 12")),
            ("Item 3. Legal Proceedings", ("Item 3. Legal Proceedings", "Page F-3")),
        )
    )
    assert toc_signals(table).strong_rows == 3


def test_unlabelled_page_shapes_stay_on_their_own_recognizers() -> None:
    # No "page" word: a bare letter page is strong via the letter
    # recognizer, a roman suffix via the TOC row patterns, bare numbers weak.
    table = _raw_table(
        (
            ("Appendix A", ("Appendix A", "F-3")),
            ("Item 1. Business", ("Item 1. Business", "iv")),
            ("Business", ("Business", "1")),
            ("Properties", ("Properties", "2")),
            ("Legal Proceedings", ("Legal Proceedings", "3")),
        )
    )
    signals = toc_signals(table)
    assert signals.strong_rows == 2
    assert signals.weak_rows == 3


def test_filing_pass_drops_all_scores_for_toc_tables() -> None:
    toc = _table(_COVER_TOC, index=6, in_span=True)
    kept = _table(_BALANCE_SHEET, index=20)
    results, scores = classify_filing([toc, kept])
    assert results[0].tier == "genre_refusal"
    assert scores[0] == {}
    assert results[1].family == "balance_sheet"
    assert scores[1]["balance_sheet"] > 0.0


def test_amount_recognizer_verdicts() -> None:
    from edgar_sec.engine.tables.extraction.seats.toc_gate import _AMOUNT_RE

    for cell in ("1,234", "1234,567", "12,345,678", "1.5", "1,234.56"):
        assert _AMOUNT_RE.search(cell), cell
    for cell in ("100", "12,34", "1,23", "abc"):
        assert not _AMOUNT_RE.search(cell), cell


def test_ref_cell_recognizer_preserved_verdicts() -> None:
    from edgar_sec.engine.tables.extraction.seats.toc_gate import _REF_CELL_RE

    assert _REF_CELL_RE.match("Note 1A")
    assert _REF_CELL_RE.match("Item 2.")
    assert not _REF_CELL_RE.match("Notes 1")
