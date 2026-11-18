"""S1 statement-summary separator: priced rules and the gate.
Each built rule fires on a synthetic member form and stays
silent on its near miss; the gate denies every stamped claim."""

from __future__ import annotations

from edgar_sec.engine.tables.ascii_html.model import (
    ResolvedGrid,
    TableGeometry,
    TableRenderResult,
)
from edgar_sec.engine.tables.extraction.competition import (
    GeometryText,
    compete,
    geometry_text_from_table,
)
from edgar_sec.engine.tables.extraction.context import SectionRef, TableContext
from edgar_sec.engine.tables.extraction.signature_profiles import (
    ContainmentEdge,
    SignatureTerm,
)
from edgar_sec.engine.tables.extraction.summary_separator import (
    SummarySeparatorResult,
    evaluate_summary_separator,
)
from edgar_sec.engine.tables.extraction.typed_rows import (
    TypedTable,
    structure_table,
)


def _table(rows: tuple[tuple[str, ...], ...], **context_kwargs: object) -> TypedTable:
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
    return structure_table(TableContext(geometry=geometry, **context_kwargs))


def _rules(table: TypedTable) -> tuple[str, ...]:
    return evaluate_summary_separator(table).rules


def test_selected_data_fires_on_the_five_year_columnar_shape() -> None:
    table = _table(
        (
            ("", "2019", "2020", "2021", "2022", "2023"),
            ("Selected financial data", "", "", "", "", ""),
            ("Revenue", "10", "11", "12", "13", "14"),
        )
    )
    assert "selected_data_present_data_years4" in _rules(table)


def test_selected_data_silent_below_four_years() -> None:
    table = _table(
        (
            ("", "2021", "2022", "2023"),
            ("Selected financial data", "", "", ""),
            ("Revenue", "10", "11", "12"),
        )
    )
    assert not evaluate_summary_separator(table).fired


def test_selected_data_last_total_at_item6() -> None:
    table = _table(
        (("Revenue", "10"), ("Total", "20")),
        section=SectionRef(item="ITEM 6", title=None),
    )
    assert "selected_data_last_total_item6" in _rules(table)


def test_mda_summar_lead_at_item7() -> None:
    rows = tuple((f"Line {i}", "1") for i in range(13))
    table = _table(
        rows,
        section=SectionRef(item="ITEM 7", title=None),
        prose_before="The following table summarizes our results.",
    )
    assert _rules(table) == ("mda_item7_summar_lead",)


def test_mda_cash_flow_activities_pair() -> None:
    table = _table(
        (
            ("Net cash provided by operating activities", "10"),
            ("Net cash used in financing activities", "(5)"),
            ("Net increase in cash", "5"),
        )
    )
    assert "mda_financing_operating_rows12" in _rules(table)


def test_mda_composed_item7_rows12() -> None:
    table = _table(
        tuple((f"Line {i}", "1") for i in range(5)),
        section=SectionRef(item="ITEM 7", title=None),
    )
    assert _rules(table) == ("mda_item7_rows12",)


def test_quarterly_named_rule_at_item8() -> None:
    table = _table(
        (("Total revenues", "10"), ("Cost of revenues", "4")),
        section=SectionRef(item="ITEM 8", title=None),
    )
    assert "quarterly_item8_total_revenues" in _rules(table)


def test_plain_table_fires_nothing() -> None:
    table = _table((("Revenue", "10"), ("Cost of revenue", "6")))
    result = evaluate_summary_separator(table)
    assert not result.fired and result.rules == ()


def test_stamp_lands_on_geometry_text() -> None:
    table = _table(
        tuple((f"Line {i}", "1") for i in range(5)),
        section=SectionRef(item="ITEM 7", title=None),
    )
    stamped = geometry_text_from_table(table)
    assert stamped.summary_separator is not None
    assert stamped.summary_separator.fired
    unstamped = geometry_text_from_table(table, evaluate_stage=False)
    assert unstamped.summary_separator is None


_TERMS = (
    SignatureTerm("lease_maturity", "caption", "operating lease", 2.5, 40, 2),
    SignatureTerm("lease_maturity", "leadin", "lease liabilities", 2.5, 35, 1),
    SignatureTerm("lease_maturity", "stub", "undiscounted lease payments", 2.5, 30, 0),
    SignatureTerm("debt_maturity", "caption", "long-term debt", 2.5, 40, 2),
    SignatureTerm("debt_maturity", "leadin", "senior notes", 2.5, 30, 1),
    SignatureTerm("debt_maturity", "stub", "aggregate maturities", 2.5, 25, 0),
    SignatureTerm("cash_flow", "stub", "cash flows", 0.4, 90, 80),
    SignatureTerm("equity_statement", "caption", "changes in equity", 2.5, 40, 1),
    SignatureTerm("equity_statement", "leadin", "statement of changes", 2.5, 38, 1),
    SignatureTerm("equity_statement", "notehead", "changes in equity", 2.5, 40, 2),
    SignatureTerm("equity_statement", "stub", "shares issued", 2.0, 30, 5),
    SignatureTerm("lease_maturity", "notehead", "leases", 2.5, 33, 1),
    SignatureTerm(
        "aoci_rollforward", "stub", "accumulated other comprehensive", 2.5, 30, 3
    ),
)

_EDGES = (
    ContainmentEdge("aoci_rollforward", "equity_statement", 0.75, "test census"),
    ContainmentEdge("equity_statement", "aoci_rollforward", 0.50, "test census"),
)


def _lease_geometry(**kwargs: object) -> GeometryText:
    return GeometryText(
        caption="Operating Lease Liabilities",
        leadin="Lease liabilities mature as follows; future cash flows are summarized.",
        stubs=("2025", "Total undiscounted lease payments"),
        **kwargs,
    )


def test_gate_denies_every_claim_and_trails_the_evidence() -> None:
    geometry = _lease_geometry(
        summary_separator=SummarySeparatorResult(
            rules=("mda_item7_rows12",), sub_masses=("MD&A-SUMMARY",)
        )
    )
    result = compete(geometry, terms=_TERMS, edges=_EDGES)
    assert result.claims == ()
    evidence = result.scores["lease_maturity"].evidence
    assert any(
        e.channel == "gate" and "summary separator" in e.detail for e in evidence
    )


def test_gate_silent_when_unstamped_or_unfired() -> None:
    unstamped = compete(_lease_geometry(), terms=_TERMS, edges=_EDGES)
    assert unstamped.claims == ("lease_maturity",)
    unfired = compete(
        _lease_geometry(summary_separator=SummarySeparatorResult()),
        terms=_TERMS,
        edges=_EDGES,
    )
    assert unfired.claims == ("lease_maturity",)
