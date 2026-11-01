"""Presentation views: rows, dimensional modes, and both parents."""

from __future__ import annotations

from typing import Any

import pyarrow.parquet as pq
import pytest

from edgar_sec.apps.client.xbrl import Xbrl
from edgar_sec.domain.identity import AccessionNumber, Cik
from edgar_sec.engine.xbrl.schema.models import FilingXbrl, LinkbaseBundle
from edgar_sec.engine.xbrl.storage.storage import presentation_arcs_from_arrow_table
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy
from tests.engine.xbrl.solve.conftest import (
    load_seed_calculation_arcs,
    load_seed_facts,
)
from tests.support import bundle_dir

_MSFT = "msft_2024_10k"
_JPM = "jpm_2024_10k"
_REVENUE = "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
_OPERATING = "us-gaap:OperatingIncomeLoss"
_NET_INCOME = "us-gaap:NetIncomeLoss"
_SEGMENT_AXIS = "us-gaap:StatementBusinessSegmentsAxis"


def _facade(folder: str, *, presentation: bool = True) -> Xbrl:
    pres_arcs = ()
    if presentation:
        table = pq.read_table(bundle_dir(folder) / "presentation_arcs.parquet")
        pres_arcs = presentation_arcs_from_arrow_table(table)
    bundle = FilingXbrl(
        accession=AccessionNumber("0000000000-24-000000"),
        cik=Cik(0),
        facts=load_seed_facts(folder),
        linkbases=LinkbaseBundle(
            calculation_arcs=load_seed_calculation_arcs(folder),
            presentation_arcs=pres_arcs,
        ),
    )
    return Xbrl(bundle, load_domain_taxonomy())


def _records(frame: Any) -> list[dict[str, Any]]:
    if hasattr(frame, "to_dicts"):
        return frame.to_dicts()
    return frame.to_dict("records")


def test_msft_income_standard_rows_carry_filed_face_values() -> None:
    """Standard mode is the tree itself: 24 rows, face facts as filed."""
    view = _facade(_MSFT).statements.view("Income Statements")
    assert view.mode == "standard"
    assert len(view.rows) == 24
    assert view.periods == ("2022-06-30", "2023-06-30", "2024-06-30")
    assert all(not row.dimensions for row in view.rows)
    revenue = view.row(_REVENUE)
    assert revenue is not None
    assert revenue.values["2024-06-30"] == 245_122_000_000
    operating = view.row(_OPERATING)
    assert operating is not None
    assert operating.values["2024-06-30"] == 109_433_000_000
    net_income = view.row(_NET_INCOME)
    assert net_income is not None
    assert net_income.values["2024-06-30"] == 88_136_000_000


def test_msft_10k_span_classes_read_annual_with_bare_periods() -> None:
    """A 10-K names ANNUAL spans; its rendered headers stay bare."""
    facade = _facade(_MSFT)
    assert facade.financials.span_class("revenue") == "ANNUAL"
    view = facade.statements.income_statement()
    assert view.span_classes == {
        "2022": "ANNUAL",
        "2023": "ANNUAL",
        "2024": "ANNUAL",
    }
    assert "FY 2024 (ANNUAL)" not in view.render_table()
    assert "FY 2024 (ANNUAL)" not in view.to_markdown()


def test_msft_income_face_totals_equal_the_calc_view() -> None:
    """Every face value matches the algebraic view's node values."""
    statements = _facade(_MSFT).statements
    view = statements.view("Income Statements")
    graph = statements.income_statement().graph
    for concept in (_REVENUE, _OPERATING, _NET_INCOME):
        row = view.row(concept)
        node = graph.nodes[concept]
        assert row is not None
        for period, value in row.values.items():
            assert node.values[period[:4]] == value


# Edgartools renders 21 / 42 / 17 for this statement. The standard gap
# is the table/axis/domain scaffolding rows this tree carries as headers.
def test_msft_income_mode_row_counts() -> None:
    """Detailed adds declared-axis breakdowns; summary keeps totals only."""
    statements = _facade(_MSFT).statements
    detailed = statements.view("Income Statements", mode="detailed")
    summary = statements.view("Income Statements", mode="summary")
    assert len(detailed.rows) == 38
    assert sum(1 for row in detailed.rows if row.dimensions) == 14
    assert len(summary.rows) == 5


def test_msft_income_summary_keeps_in_role_calc_totals() -> None:
    """Summary totals are the concepts parenting others within the role."""
    view = _facade(_MSFT).statements.view("Income Statements", mode="summary")
    assert {row.concept for row in view.rows} == {
        "us-gaap:GrossProfit",
        _OPERATING,
        "us-gaap:IncomeLossFromContinuingOperationsBeforeIncomeTaxes"
        "ExtraordinaryItemsNoncontrollingInterest",
        _NET_INCOME,
        "us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding",
    }
    assert view.row(_REVENUE) is None
    net_income = view.row(_NET_INCOME)
    assert net_income is not None
    assert net_income.values["2024-06-30"] == 88_136_000_000


def test_abstract_rows_are_headers_without_values() -> None:
    """Abstract and scaffolding rows head sections and carry no values."""
    view = _facade(_MSFT).statements.view("Income Statements")
    root = view.rows[0]
    assert root.concept == "us-gaap:IncomeStatementAbstract"
    assert root.abstract
    assert root.values == {}
    assert root.presentation_parent is None
    assert root.depth == 0
    eps = view.row("us-gaap:EarningsPerShareAbstract")
    assert eps is not None
    assert eps.abstract
    assert eps.values == {}


def test_rows_carry_both_parents() -> None:
    """Each row names its presentation parent and its calculation parent."""
    view = _facade(_MSFT).statements.view("Income Statements")
    revenue = view.row(_REVENUE)
    assert revenue is not None
    assert revenue.presentation_parent == "us-gaap:StatementLineItems"
    assert revenue.calculation_parent == "us-gaap:GrossProfit"
    frame = view.to_dataframe()
    assert list(frame.columns) == [
        "label",
        "concept",
        "2022-06-30",
        "2023-06-30",
        "2024-06-30",
        "presentation_parent",
        "calculation_parent",
    ]
    record = next(r for r in _records(frame) if r["concept"] == _REVENUE)
    assert record["2024-06-30"] == 245_122_000_000
    assert record["calculation_parent"] == "us-gaap:GrossProfit"


def test_segment_role_detailed_breakdowns_carry_axis_members() -> None:
    """The segment role's breakdown rows expose axis and member columns."""
    statements = _facade(_MSFT).statements
    standard = statements.view("Segment Revenue Detail")
    detailed = statements.view("Segment Revenue Detail", mode="detailed")
    assert len(standard.rows) == 9
    assert len(detailed.rows) == 12
    breakdowns = [row for row in detailed.rows if row.dimensions]
    assert breakdowns
    assert all(dict(row.dimensions) for row in breakdowns)
    assert {axis for row in breakdowns for axis, _ in row.dimensions} == {_SEGMENT_AXIS}
    cloud = next(
        row
        for row in breakdowns
        if dict(row.dimensions)[_SEGMENT_AXIS] == "msft:IntelligentCloudMember"
    )
    assert cloud.presentation_parent == _REVENUE
    assert cloud.values["2024-06-30"] == 105_362_000_000
    frame = detailed.to_dataframe()
    assert _SEGMENT_AXIS in frame.columns
    record = next(r for r in _records(frame) if r[_SEGMENT_AXIS] == "Intelligent Cloud")
    assert record["concept"] == _REVENUE
    assert record["2024-06-30"] == 105_362_000_000


def test_render_ascii_shows_title_mode_and_values() -> None:
    """The ASCII table heads with title and mode and prints filed values."""
    statements = _facade(_MSFT).statements
    text = statements.view("Income Statements").render_ascii()
    assert "INCOME STATEMENTS" in text
    assert "STANDARD" in text
    assert "(in millions)" in text
    assert "$245,122" in text
    full = statements.view("Income Statements").render_ascii(scaled=False)
    assert "$245,122,000,000" in full
    detailed = statements.view("Income Statements", mode="detailed").render_ascii()
    assert "Product Or Service: Product" in detailed


def test_render_ascii_wraps_long_concept_labels() -> None:
    """Long labels wrap on word boundaries instead of truncating."""
    statements = _facade(_MSFT).statements
    text = statements.view("Income Statements").render_ascii()
    assert "Revenue From Contract With Customer" in text
    assert "Excluding Assessed Tax" in text


def test_markdown_export_matches_scaled_face_totals() -> None:
    """Markdown rows parse as pipes and carry the scaled face totals."""
    view = _facade(_MSFT).statements.view("Income Statements")
    md = view.to_markdown()
    assert md.startswith("MICROSOFT CORPORATION")
    assert "(in millions)" in md
    pipe_lines = [line for line in md.splitlines() if line.startswith("|")]
    assert pipe_lines[0].startswith("| Financial Concept | Concept |")
    revenue = next(line for line in pipe_lines if _REVENUE in line)
    cells = [cell.strip() for cell in revenue.strip().strip("|").split("|")]
    label = "Revenue From Contract With Customer Excluding Assessed Tax"
    assert cells[0].strip() == label
    assert cells[4] == "$245,122"
    assert "$245,122,000,000" in view.to_markdown(scaled=False)


def test_view_rejects_unknown_role_mode_and_empty_catalog() -> None:
    """Unknown roles and modes raise; an empty catalog has no view."""
    statements = _facade(_MSFT).statements
    with pytest.raises(ValueError, match="no presentation role"):
        statements.view("No Such Role")
    with pytest.raises(ValueError, match="unknown presentation mode"):
        statements.view("Income Statements", mode="bogus")
    bare = _facade(_MSFT, presentation=False).statements
    with pytest.raises(ValueError, match="no presentation role"):
        bare.view("Income Statements")


def test_jpm_income_view_builds_with_filed_values() -> None:
    """JPM's income role renders its tree with the filed net income."""
    statements = _facade(_JPM).statements
    entry = next(
        entry
        for entry in statements.by_category("statement")
        if entry.family == "IncomeStatement"
    )
    view = statements.view(entry.role_uri)
    assert len(view.rows) == 35
    assert view.periods == ("2022-12-31", "2023-12-31", "2024-12-31")
    net_income = view.row(_NET_INCOME)
    assert net_income is not None
    assert net_income.values["2024-12-31"] == 58_471_000_000
