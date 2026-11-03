"""Tests for the filed dei period/fiscal metadata reader."""

from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.engine.xbrl.normalize.filed_metadata import (
    filed_metadata,
    fiscal_year_containing,
    focus_length_class,
)
from edgar_sec.engine.xbrl.schema.models import XbrlFact

_ACC = AccessionNumber("0000000000-24-000000")


def _fact(qname: str, value: object, **kwargs: object) -> XbrlFact:
    """One fact on the standard cover context."""
    return XbrlFact(
        accession=_ACC,
        concept_qname=qname,
        value=value,  # type: ignore[arg-type]
        period_type="duration",
        start_date="2026-07-01",
        end_date="2026-09-30",
        **kwargs,  # type: ignore[arg-type]
    )


def test_reads_the_period_fiscal_block() -> None:
    """A complete 10-Q cover yields every field, coerced."""
    facts = (
        _fact("dei:DocumentPeriodEndDate", "2026-09-30"),
        _fact("dei:DocumentFiscalYearFocus", "2027"),
        _fact("dei:DocumentFiscalPeriodFocus", "Q1"),
        _fact("dei:DocumentType", "10-Q"),
        _fact("dei:CurrentFiscalYearEndDate", "--06-30"),
        _fact("dei:DocumentQuarterlyReport", "true"),
        _fact("dei:DocumentTransitionReport", "false"),
        _fact("dei:AmendmentFlag", "false"),
        _fact("us-gaap:Revenues", 92.279e9),
    )
    meta = filed_metadata(facts)
    assert meta.period_end == "2026-09-30"
    assert meta.fiscal_year == 2027
    assert meta.period_focus == "Q1"
    assert meta.document_type == "10-Q"
    assert meta.fiscal_year_end == (6, 30)
    assert meta.quarterly_report is True
    assert meta.annual_report is None
    assert meta.transition_report is False
    assert meta.amendment is False


def test_coerces_numeric_year_and_bool_values() -> None:
    """Float-parsed gYear foci and native bools coerce to int and bool."""
    facts = (
        _fact("dei:DocumentFiscalYearFocus", 2027.0),
        _fact("dei:DocumentAnnualReport", True),
    )
    meta = filed_metadata(facts)
    assert meta.fiscal_year == 2027
    assert meta.annual_report is True


def test_absent_block_is_all_none() -> None:
    """A filing with no dei cover facts yields an all-None record."""
    meta = filed_metadata((_fact("us-gaap:Revenues", 1.0),))
    assert meta.period_end is None
    assert meta.fiscal_year is None
    assert meta.period_focus is None
    assert meta.fiscal_year_end is None


def test_undimensioned_value_wins_over_dimensioned() -> None:
    """A dimensioned duplicate never overrides the cover's own value."""
    facts = (
        _fact("dei:DocumentPeriodEndDate", "2026-09-30"),
        _fact(
            "dei:DocumentPeriodEndDate",
            "2025-09-30",
            dimensions={"us-gaap:Axis": "us-gaap:Member"},
        ),
    )
    assert filed_metadata(facts).period_end == "2026-09-30"


def test_earlier_fye_name_and_full_date_parse() -> None:
    """The earlier FYE concept name and a full-date value both parse."""
    facts = (_fact("dei:EntityFiscalYearEndDate", "2026-09-26"),)
    assert filed_metadata(facts).fiscal_year_end == (9, 26)


def test_fiscal_year_containing_windows() -> None:
    """The FYE window names the fiscal year by its ending calendar year."""
    assert fiscal_year_containing("2026-09-30", (6, 30)) == 2027
    assert fiscal_year_containing("2026-06-30", (6, 30)) == 2026
    assert fiscal_year_containing("2026-06-30", (12, 31)) == 2026
    assert fiscal_year_containing("2027-01-15", (1, 31)) == 2027


def test_focus_length_class_mapping() -> None:
    """Filed foci map to the length classes the probe measured."""
    assert focus_length_class("Q1") == "QUARTER"
    assert focus_length_class("Q2") == "YTD_2Q"
    assert focus_length_class("Q3") == "YTD_3Q"
    assert focus_length_class("FY") == "ANNUAL"
    assert focus_length_class("Q4") is None
    assert focus_length_class(None) is None
