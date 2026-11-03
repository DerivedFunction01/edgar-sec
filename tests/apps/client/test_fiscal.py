"""Fiscal-year query seams: dei window, focus class, instant refusal."""

from __future__ import annotations

from edgar_sec.apps.client.fiscal import filed_length_class, transition_length_class
from edgar_sec.apps.client.xbrl import Xbrl
from edgar_sec.domain.identity import AccessionNumber, Cik
from edgar_sec.engine.xbrl.normalize.filed_metadata import (
    filed_metadata as read_filed_metadata,
)
from edgar_sec.engine.xbrl.schema.models import FilingXbrl, LinkbaseBundle, XbrlFact
from edgar_sec.engine.xbrl.solve.query import QueryStatus
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy

_ACCESSION = "0000000000-26-000001"


def _fact(
    qname: str,
    value: object,
    *,
    start: str | None = None,
    end: str | None = None,
    instant: str | None = None,
    unit: str | None = "USD",
) -> XbrlFact:
    return XbrlFact(
        accession=AccessionNumber(_ACCESSION),
        concept_qname=qname,
        value=value,
        unit=unit,
        period_type="instant" if instant is not None else "duration",
        start_date=start,
        end_date=end,
        instant_date=instant,
    )


def _dei(
    period_end: str, fiscal_year: int, focus: str, fye: str
) -> tuple[XbrlFact, ...]:
    cover = {"instant": period_end, "unit": None}
    return (
        _fact("dei:DocumentPeriodEndDate", period_end, **cover),
        _fact("dei:DocumentFiscalYearFocus", fiscal_year, **cover),
        _fact("dei:DocumentFiscalPeriodFocus", focus, **cover),
        _fact("dei:CurrentFiscalYearEndDate", fye, **cover),
    )


def _facade(facts: tuple[XbrlFact, ...]) -> Xbrl:
    bundle = FilingXbrl(
        accession=AccessionNumber(_ACCESSION),
        cik=Cik(0),
        facts=facts,
        linkbases=LinkbaseBundle(),
    )
    return Xbrl(bundle, load_domain_taxonomy())


def test_dei_window_enumerates_non_december_fye_interim() -> None:
    """Verify a June-FYE Q1 filing answers at its dei fiscal year."""
    facts = _dei("2026-09-30", 2027, "Q1", "--06-30") + (
        _fact("us-gaap:Revenues", 92.0, start="2026-07-01", end="2026-09-30"),
        _fact(
            "us-gaap:RevenueRemainingPerformanceObligation",
            683.0,
            instant="2026-09-30",
        ),
    )
    result = _facade(facts).query("revenue", fiscal_year=2027)
    assert result.status == QueryStatus.REPORTED
    assert result.value == 92.0


def test_failed_duration_tier_never_serves_an_instant_substitute() -> None:
    """Verify an unfiled focus class refuses instead of serving RPO."""
    facts = _dei("2026-06-30", 2026, "Q2", "--12-31") + (
        _fact("us-gaap:Revenues", 20.0, start="2026-04-01", end="2026-06-30"),
        _fact(
            "us-gaap:RevenueRemainingPerformanceObligation",
            44.0,
            instant="2026-06-30",
        ),
    )
    result = _facade(facts).query("revenue", fiscal_year=2026)
    assert result.status == QueryStatus.UNAVAILABLE
    assert result.value is None


def test_instant_term_still_serves_from_the_instant_tier() -> None:
    """Verify a balance-sheet term is not refused by the duration fix."""
    facts = _dei("2026-09-30", 2027, "Q1", "--06-30") + (
        _fact("us-gaap:Revenues", 92.0, start="2026-07-01", end="2026-09-30"),
        _fact("us-gaap:Assets", 512.0, instant="2026-09-30"),
    )
    result = _facade(facts).query("us-gaap:Assets", fiscal_year=2027)
    assert result.status == QueryStatus.REPORTED
    assert result.value == 512.0


def test_uncorroborated_focus_class_is_not_adopted() -> None:
    """Verify a longer cumulative span at period end vetoes the focus class."""
    facts = _dei("2024-06-29", 2024, "Q3", "--09-28") + (
        _fact("us-gaap:Revenues", 39.0, start="2023-10-01", end="2024-06-29"),
        _fact(
            "us-gaap:CommonStockDividendsPerShareDeclared",
            1.0,
            start="2022-07-01",
            end="2024-06-29",
            unit="USD/shares",
        ),
    )
    result = _facade(facts).query("revenue", fiscal_year=2024)
    assert result.status == QueryStatus.UNAVAILABLE
    assert result.value is None


def test_event_dated_filing_without_dei_focus_keeps_annual_default() -> None:
    """Verify a dei-silent 8-K shape serves its annual span, not a stub."""
    cover = {"instant": "2026-10-28", "unit": None}
    facts = (
        _fact("dei:DocumentPeriodEndDate", "2026-10-28", **cover),
        _fact("dei:DocumentType", "8-K", **cover),
        _fact("us-gaap:Revenues", 331.0, start="2025-07-01", end="2026-06-30"),
        _fact(
            "us-gaap:RevenueRemainingPerformanceObligation",
            684.0,
            start="2026-10-28",
            end="2026-10-28",
        ),
    )
    result = _facade(facts).query("revenue", fiscal_year=2026)
    assert result.status == QueryStatus.REPORTED
    assert result.value == 331.0


def test_start_year_named_annual_span_enumerates_in_its_dei_window() -> None:
    """Verify a Jan-FYE filer's FY2025 span ending in 2026 answers FY2025."""
    facts = _dei("2026-01-31", 2025, "FY", "--01-31") + (
        _fact("us-gaap:Revenues", 100.0, start="2025-02-01", end="2026-01-31"),
    )
    result = _facade(facts).query("revenue", fiscal_year=2025)
    assert result.status == QueryStatus.REPORTED
    assert result.value == 100.0


def _transition_facts(document_type: str) -> tuple[XbrlFact, ...]:
    """An FYE-change stub year: FY focus, no ladder-annual span in the year."""
    cover = {"instant": "2012-06-30", "unit": None}
    return (
        _fact("dei:DocumentType", document_type, **cover),
        *_dei("2012-06-30", 2012, "FY", "--06-30"),
        _fact("us-gaap:Revenues", 6004.0, start="2011-01-01", end="2011-12-31"),
        _fact("us-gaap:Revenues", 2726.0, start="2011-01-01", end="2011-06-30"),
        _fact("us-gaap:Revenues", 2071.0, start="2012-01-01", end="2012-06-30"),
    )


def test_transition_filing_serves_its_stub_year() -> None:
    """Verify a 10-KT fiscal-year query answers from the transition stub."""
    result = _facade(_transition_facts("10-KT")).query("revenue", fiscal_year=2012)
    assert result.status == QueryStatus.REPORTED
    assert result.value == 2071.0


def test_non_transition_twin_keeps_the_empty_tier() -> None:
    """Verify the stub fallback is gated on the transition document type."""
    result = _facade(_transition_facts("10-K")).query("revenue", fiscal_year=2012)
    assert result.status == QueryStatus.UNAVAILABLE
    assert result.value is None


def test_transition_fallback_skips_off_focus_class_requests() -> None:
    """Verify an explicit QUARTER request on a 10-KT keeps the empty tier."""
    result = _facade(_transition_facts("10-KT")).query(
        "revenue", fiscal_year=2012, length_class="QUARTER"
    )
    assert result.status == QueryStatus.UNAVAILABLE
    assert result.value is None


def test_filed_length_class_names_the_corroborated_focus() -> None:
    """Verify the module derivation names a Q1 focus its spans support."""
    facts = _dei("2026-09-30", 2027, "Q1", "--06-30") + (
        _fact("us-gaap:Revenues", 92.0, start="2026-07-01", end="2026-09-30"),
    )
    metadata = read_filed_metadata(facts)
    assert filed_length_class(facts, metadata) == "QUARTER"
    facade = _facade(facts)
    assert facade.financials.filed_length_class() == "QUARTER"
    assert facade.financials.transition_length_class() is None


def test_filed_length_class_refuses_an_uncorroborated_focus() -> None:
    """Verify a longer cumulative span at period end vetoes the derivation."""
    facts = _dei("2024-06-29", 2024, "Q3", "--09-28") + (
        _fact("us-gaap:Revenues", 39.0, start="2023-10-01", end="2024-06-29"),
        _fact(
            "us-gaap:CommonStockDividendsPerShareDeclared",
            1.0,
            start="2022-07-01",
            end="2024-06-29",
            unit="USD/shares",
        ),
    )
    assert filed_length_class(facts, read_filed_metadata(facts)) is None


def test_transition_length_class_names_the_stub_only_on_transition_forms() -> None:
    """Verify the stub class is named on a 10-KT and refused on its twin."""
    facts = _transition_facts("10-KT")
    assert transition_length_class(facts, read_filed_metadata(facts)) == "YTD_2Q"
    assert _facade(facts).financials.transition_length_class() == "YTD_2Q"
    twin = _transition_facts("10-K")
    assert transition_length_class(twin, read_filed_metadata(twin)) is None
