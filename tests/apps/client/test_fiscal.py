"""Fiscal-year query seams: dei window, focus class, instant refusal."""

from __future__ import annotations

from edgar_sec.apps.client.xbrl import Xbrl
from edgar_sec.domain.identity import AccessionNumber, Cik
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
