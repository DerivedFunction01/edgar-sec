"""Tests for the cross-form census filing analysis."""

from pathlib import Path

from edgar_sec.domain.identity import AccessionNumber, Cik
from edgar_sec.engine.xbrl.discovery.cohort import SeedFiling
from edgar_sec.engine.xbrl.schema.models import XbrlFact
from edgar_sec.engine.xbrl.solve.scoping import FilingRef, build_lineages
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy
from edgar_sec.pipelines.xbrl_review.bundles import LoadedFiling
from edgar_sec.domain.forms.common.aliases import is_transition_form
from edgar_sec.tools.xbrl_eval.xbrl_cross_form_census import (
    _pair_evaluation,
    _transition_shape,
    analyze_facts,
    dei_metadata_present,
)

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


def test_dei_metadata_present_reads_only_the_metadata_family():
    """Presence covers the period/fiscal concepts, not other dei facts."""
    facts = (
        _fact("dei:DocumentPeriodEndDate", "2026-03-31"),
        _fact("dei:DocumentType", "10-Q"),
        _fact("dei:EntityRegistrantName", "Example Co"),
        _fact("us-gaap:Revenues", 5.0),
    )
    assert dei_metadata_present(facts) == {"DocumentPeriodEndDate", "DocumentType"}
    assert dei_metadata_present(()) == set()


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


def test_transition_form_detection_uses_the_alias_registry():
    """T-variants of periodic families are transition forms; others not."""
    assert is_transition_form("10-KT")
    assert is_transition_form("10-QT/A")
    assert is_transition_form("11-KT")
    assert not is_transition_form("10-K")
    assert not is_transition_form("10-K/A")
    assert not is_transition_form("10-KSB")
    assert not is_transition_form("8-K")
    assert not is_transition_form("N-CSR")
    assert not is_transition_form("DEF 14A")
    assert not is_transition_form("424B2")


def test_transition_shape_prefers_the_filed_focus_class():
    """A transition stub shaped like YTD_2Q classifies by dei focus (FY)."""
    facts = (
        _fact("dei:DocumentFiscalPeriodFocus", "FY", start=None, end=None),
        _fact("us-gaap:Revenues", 10.0, start="2023-07-01", end="2023-12-31"),
    )
    assert _transition_shape(facts, "ytd") == "annual"


def test_transition_shape_falls_back_to_span_when_focus_unmapped():
    """An unmapped focus (Q4) leaves the span-derived shape in place."""
    facts = (
        _fact("dei:DocumentFiscalPeriodFocus", "Q4", start=None, end=None),
        _fact("us-gaap:Revenues", 10.0, start="2023-10-01", end="2023-12-31"),
    )
    assert _transition_shape(facts, "quarterly") == "quarterly"


def _seed(accession: str, form: str) -> SeedFiling:
    return SeedFiling(
        firm="ADM",
        company_name="Archer-Daniels-Midland Co",
        cik=Cik.from_raw("7084"),
        sic_code=2040,
        sector="Agriculture",
        fy=2023,
        form=form,
        accession=AccessionNumber.from_any(accession),
        sec_filing_url="https://www.sec.gov/Archives/edgar/data/7084/",
    )


def _loaded(accession: str, form: str, facts) -> LoadedFiling:
    return LoadedFiling(
        seed=_seed(accession, form),
        bundle_dir=Path("/tmp"),
        facts=tuple(facts),
        calc_arcs=(),
        declarations={},
    )


def _income(accession: str, value: float) -> XbrlFact:
    return XbrlFact(
        accession=AccessionNumber.from_any(accession),
        concept_qname="us-gaap:NetIncomeLoss",
        value=value,
        unit="USD",
        period_type="duration",
        start_date="2023-04-01",
        end_date="2023-06-30",
    )


def test_pair_evaluation_answers_from_the_restated_population():
    """Pooled pair legs agree with the amendment; no mixed population."""
    orig_acc, amend_acc = "0000007084-23-000028", "0000007084-23-000033"
    original = _loaded(orig_acc, "10-Q", [_income(orig_acc, 100.0)])
    amendment = _loaded(amend_acc, "10-Q/A", [_income(amend_acc, 120.0)])
    lineage = build_lineages(
        [
            FilingRef(orig_acc, "7084", "10-Q", "2023-06-30", "2023-08-01"),
            FilingRef(amend_acc, "7084", "10-Q/A", "2023-06-30", "2023-11-01"),
        ]
    )[0]
    evaluation = _pair_evaluation(original, amendment, lineage, load_domain_taxonomy())
    assert evaluation["classification"] == "correct"
    assert evaluation["form"] == "10-Q+10-Q/A"
    assert evaluation["pair"]["key_mixed"] is False
    assert evaluation["pair"]["mixed_legs"] == []
    assert evaluation["pair"]["served_legs"] > 0
