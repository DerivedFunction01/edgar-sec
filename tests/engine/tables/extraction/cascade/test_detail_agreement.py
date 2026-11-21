"""Detail agreement: a breakdown is claimed by its host family."""

from __future__ import annotations

from edgar_sec.engine.tables.ascii_html.model.model import (
    ResolvedGrid,
    TableGeometry,
    TableRenderResult,
)
from edgar_sec.engine.tables.extraction.cascade.scoring.classify import (
    candidate_scores,
    classify_filing,
)
from edgar_sec.engine.tables.extraction.core.text.context import TableContext
from edgar_sec.engine.tables.extraction.cascade.geometry.detail_agreement import (
    DETAIL_AGREEMENT_FLOOR,
    DETAIL_AGREEMENT_POINTS,
    find_detail_agreement,
)
from edgar_sec.engine.tables.extraction.core.registry import ASSIGNMENT_FLOOR
from edgar_sec.engine.tables.extraction.core.typed_rows import (
    TypedTable,
    structure_table,
)


def _table(rows: tuple[tuple[str, ...], ...]) -> TypedTable:
    geometry = TableGeometry(
        table_index=0,
        render_result=TableRenderResult(
            ascii_text="",
            resolved_grid=ResolvedGrid(
                rows=rows,
                column_alignments=(),
                column_widths=(),
                header_row_count=0,
            ),
            confidence=1.0,
        ),
    )
    return structure_table(TableContext(geometry=geometry))


_HOST = _table(
    (
        ("Product revenue", "600"),
        ("Service revenue", "400"),
        ("Total revenues", "1,000"),
        ("Cost of revenues", "400"),
        ("Gross profit", "600"),
        ("Operating expenses", "450"),
        ("Income from operations", "150"),
        ("Net income", "120"),
    )
)

_DETAIL = _table(
    (
        ("Product A", "250"),
        ("Product B", "350"),
        ("Total product revenue", "600"),
    )
)


def test_detail_closes_to_the_host_line() -> None:
    agreement = find_detail_agreement(_DETAIL, [("income_statement", _HOST)])
    assert agreement is not None
    assert agreement.host_family == "income_statement"
    assert agreement.host_label == "product revenue"


def test_ambiguous_agreement_claims_nothing() -> None:
    balance = _table(
        (
            ("Cash and equivalents", "600"),
            ("Total assets", "5,000"),
        )
    )
    hosts = [("income_statement", _HOST), ("balance_sheet", balance)]
    assert find_detail_agreement(_DETAIL, hosts) is None


def test_sum_only_closure_needs_three_components() -> None:
    two = _table((("Product A", "250"), ("Product B", "350")))
    assert find_detail_agreement(two, [("income_statement", _HOST)]) is None
    three = _table((("Product A", "250"), ("Product B", "200"), ("Product C", "150")))
    agreement = find_detail_agreement(three, [("income_statement", _HOST)])
    assert agreement is not None


def test_stated_total_must_close_to_its_components() -> None:
    broken = _table(
        (
            ("Product A", "250"),
            ("Product B", "300"),
            ("Total product revenue", "600"),
        )
    )
    assert find_detail_agreement(broken, [("income_statement", _HOST)]) is None


def test_small_values_never_agree() -> None:
    host = _table((("Other income", "12"), ("Net income", "120")))
    detail = _table((("Part A", "5"), ("Part B", "7"), ("Total other", "12")))
    assert find_detail_agreement(detail, [("income_statement", host)]) is None


def test_filing_pass_adds_the_agreement_evidence() -> None:
    results, scores = classify_filing([_HOST, _DETAIL])
    assert results[0].family == "income_statement"
    before = candidate_scores(_DETAIL)["income_statement"][0]
    assert scores[1]["income_statement"] == before + DETAIL_AGREEMENT_POINTS
    trail = results[1].evidence
    assert any("detail agreement" in ev.detail for ev in trail)


def test_detail_seat_clears_the_detail_floor_not_the_assignment_floor() -> None:
    before = candidate_scores(_DETAIL)["income_statement"][0]
    assert before == 0.0
    results, scores = classify_filing([_HOST, _DETAIL])
    assert scores[1]["income_statement"] == DETAIL_AGREEMENT_FLOOR
    assert DETAIL_AGREEMENT_FLOOR < ASSIGNMENT_FLOOR
    assert results[1].family == "income_statement"
    assert results[1].tier == "evidence"
    assert results[1].score == DETAIL_AGREEMENT_FLOOR


def test_detail_seat_keeps_score_arbitration() -> None:
    detail = _table(
        (
            ("Depreciation", "250"),
            ("Amortization", "350"),
            ("Total product revenue", "600"),
        )
    )
    assert find_detail_agreement(detail, [("income_statement", _HOST)]) is not None
    results, scores = classify_filing([_HOST, detail])
    assert scores[1]["income_statement"] == DETAIL_AGREEMENT_FLOOR
    assert scores[1]["deferred_tax"] > scores[1]["income_statement"]
    assert results[1].family != "income_statement"
    assert results[1].tier == "residual"
