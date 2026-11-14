"""Section-position gate: MD&A refusals, silent elsewhere."""

from __future__ import annotations

from edgar_sec.domain.forms.families.annual.location import section_scopes
from edgar_sec.engine.tables.ascii_html.model import (
    ResolvedGrid,
    TableGeometry,
    TableRenderResult,
)
from edgar_sec.engine.tables.extraction.classify import (
    classify_filing,
    classify_table,
)
from edgar_sec.engine.tables.extraction.context import (
    SectionRef,
    TableContext,
)
from edgar_sec.engine.tables.extraction.policy import ClassificationPolicy
from edgar_sec.engine.tables.extraction.section_gate import (
    SectionScope,
    genre_refusal,
    section_scope,
)
from edgar_sec.engine.tables.extraction.typed_rows import (
    CaptionInfo,
    ColumnPeriod,
    RowKind,
    TypedRow,
    TypedTable,
)

SCOPES = section_scopes()
POLICY = ClassificationPolicy(section_scopes=SCOPES)

_INCOME = (
    "Revenues",
    "Cost of revenues",
    "Gross profit",
    "Operating expenses",
    "Total operating expenses",
    "Operating income",
    "Net income",
)


def test_declared_map_scopes() -> None:
    fs = SectionScope.FINANCIAL_STATEMENTS
    assert section_scope(SCOPES, "10-K", None, "ITEM 8") is fs
    assert section_scope(SCOPES, "10-K", None, "ITEM 15") is fs
    assert section_scope(SCOPES, "10-K", None, "ITEM 16") is fs
    assert section_scope(SCOPES, "10-K/A", None, "ITEM 7") is SectionScope.MDA
    assert section_scope(SCOPES, "10-K", None, "ITEM 7A") is SectionScope.MDA
    assert (
        section_scope(SCOPES, "10-Q", "PART I", "ITEM 1")
        is SectionScope.FINANCIAL_STATEMENTS
    )
    assert section_scope(SCOPES, "10-Q/A", "PART I", "ITEM 2") is SectionScope.MDA
    assert section_scope(SCOPES, "10-Q", "PART II", "ITEM 2") is SectionScope.OTHER
    assert section_scope(SCOPES, "10-K", None, "ITEM 1") is SectionScope.OTHER
    assert section_scope(SCOPES, "10-K", None, None) is SectionScope.UNKNOWN
    assert section_scope(SCOPES, None, None, None) is SectionScope.UNKNOWN


def test_section_title_decides_ahead_of_the_item_map() -> None:
    title = "MANAGEMENT'S DISCUSSION AND ANALYSIS OF FINANCIAL CONDITION"
    assert section_scope(SCOPES, "10-K", None, "ITEM 8", title) is SectionScope.MDA
    part = section_scope(SCOPES, "10-Q", "PART II", "ITEM 6", title)
    assert part is SectionScope.MDA
    fs_title = "FINANCIAL STATEMENTS AND SUPPLEMENTARY DATA"
    titled = section_scope(SCOPES, "10-K", None, "ITEM 7", fs_title)
    assert titled is SectionScope.FINANCIAL_STATEMENTS


def test_refusal_only_for_statement_families_at_mda() -> None:
    refusal = genre_refusal(SCOPES, "income_statement", "10-K", None, "ITEM 7")
    assert refusal is not None
    assert refusal.family == "income_statement"
    assert "ITEM 7" in refusal.detail
    assert genre_refusal(SCOPES, "segment_reporting", "10-K", None, "ITEM 7") is None
    assert genre_refusal(SCOPES, "pension", "10-K", None, "ITEM 7") is None
    assert genre_refusal(SCOPES, "income_statement", "10-K", None, "ITEM 8") is None
    assert genre_refusal(SCOPES, "income_statement", "10-K", None, "ITEM 1") is None
    assert genre_refusal(SCOPES, "income_statement", None, None, None) is None


def test_no_declared_map_no_refusal() -> None:
    assert genre_refusal((), "income_statement", "10-K", None, "ITEM 7") is None


def _table(
    labels: tuple[str, ...],
    *,
    section: SectionRef | None = None,
    caption_titles: tuple[str, ...] = (),
) -> TypedTable:
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
    context = TableContext(geometry=geometry, section=section)
    rows = tuple(
        TypedRow(
            label=label,
            values=(1.0,),
            kind=RowKind.DATA,
            raw=(label, "1"),
        )
        for label in labels
    )
    return TypedTable(
        context=context,
        caption=CaptionInfo(
            lines=(),
            company=None,
            titles=caption_titles,
            audit_status=None,
            scale=None,
            continued=False,
            consumed_rows=0,
        ),
        periods=(
            ColumnPeriod(1, None, "2024", "2024"),
            ColumnPeriod(2, None, "2023", "2023"),
        ),
        rows=rows,
        scale=None,
        header_rows=0,
        continued=False,
    )


def test_income_claim_at_mda_position_is_refused_and_recorded() -> None:
    table = _table(_INCOME, section=SectionRef("ITEM 7", None, "10-K", None))
    result = classify_table(table, POLICY)
    assert result.family == "other"
    assert result.tier == "genre_refusal"
    assert any(
        entry.group == "genre_refusal" and "ITEM 7" in entry.detail
        for entry in result.evidence
    )


def test_income_claim_inside_financial_statements_stands() -> None:
    table = _table(_INCOME, section=SectionRef("ITEM 8", None, "10-K", None))
    result = classify_table(table, POLICY)
    assert result.family == "income_statement"
    assert result.tier == "evidence"


def test_income_claim_at_quarterly_mda_position_is_refused() -> None:
    table = _table(_INCOME, section=SectionRef("ITEM 2", None, "10-Q", "PART I"))
    assert classify_table(table, POLICY).tier == "genre_refusal"
    part_two = _table(_INCOME, section=SectionRef("ITEM 2", None, "10-Q", "PART II"))
    assert classify_table(part_two, POLICY).family == "income_statement"


def test_mda_caption_stack_refuses_without_a_form_stamp() -> None:
    table = _table(
        _INCOME,
        section=SectionRef(None, None),
        caption_titles=("Management's Discussion and Analysis",),
    )
    assert classify_table(table, POLICY).tier == "genre_refusal"


def test_filing_pass_drops_refused_statement_scores() -> None:
    refused = _table(_INCOME, section=SectionRef("ITEM 7", None, "10-K", None))
    kept = _table(_INCOME, section=SectionRef("ITEM 8", None, "10-K", None))
    results, scores = classify_filing([refused, kept], POLICY)
    assert results[0].tier == "genre_refusal"
    assert "income_statement" not in scores[0]
    assert results[1].family == "income_statement"
    assert scores[1]["income_statement"] > 0.0
