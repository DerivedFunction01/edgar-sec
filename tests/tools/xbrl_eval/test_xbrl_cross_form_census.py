"""Tests for the cross-form census filing analysis."""

from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.engine.xbrl.schema.models import XbrlFact
from edgar_sec.tools.xbrl_eval.xbrl_cross_form_census import analyze_facts

ACC = AccessionNumber("0000000000-26-000001")


def _fact(qname, value, *, dims=None, start="2026-01-01", end="2026-03-31"):
    """One synthetic fact in a quarterly duration period by default."""
    return XbrlFact(
        accession=ACC,
        concept_qname=qname,
        value=value,
        period_type="duration",
        start_date=start,
        end_date=end,
        dimensions=dims or {},
    )


def test_statement_filing_primary_block_and_quarantine():
    """A us-gaap statement filing: primary us-gaap, quarterly shape."""
    facts = tuple(_fact(f"us-gaap:Concept{i}", float(i)) for i in range(30)) + (
        _fact("us-gaap:SegmentRevenue", 5.0, dims={"Segment": "A"}),
        _fact("dei:EntityCommonStockSharesOutstanding", "text"),
    )
    analysis = analyze_facts(facts)
    assert analysis["statement"] is True
    assert analysis["primary"] == "us-gaap"
    block = analysis["blocks"]["us-gaap"]
    assert block["period_shape"] == "quarterly"
    assert block["quarantined_facts"] == 1
    assert block["numeric_facts"] == 31


def test_cover_only_filing_is_dei_absence():
    """A dei-only filing: no statement block, primary dei."""
    facts = tuple(_fact(f"dei:Cover{i}", "text") for i in range(12))
    analysis = analyze_facts(facts)
    assert analysis["statement"] is False
    assert analysis["primary"] == "dei"


def test_closed_set_filing_primary_is_its_taxonomy():
    """An ecd filing with dei cover: primary ecd, not dei."""
    facts = tuple(_fact(f"dei:Cover{i}", "text") for i in range(10)) + tuple(
        _fact(f"ecd:PayVsPerformance{i}", float(i)) for i in range(20)
    )
    analysis = analyze_facts(facts)
    assert analysis["statement"] is False
    assert analysis["primary"] == "ecd"
