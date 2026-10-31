"""Tests for polymorphic form report projections."""

from __future__ import annotations

from edgar_sec.domain.document.aggregate import FilingAggregate
from edgar_sec.domain.forms.families.annual.reports import AnnualReport
from edgar_sec.domain.forms.families.current.reports import CurrentReport
from edgar_sec.domain.forms.families.ownership.reports import OwnershipReport
from edgar_sec.domain.forms.families.quarterly.reports import QuarterlyReport
from edgar_sec.domain.forms.reports import (
    CompanyReport,
    GenericReport,
    get_report_projection,
)
from edgar_sec.domain.identity import AccessionNumber, Cik


def test_ownership_form_projects_to_ownership_report() -> None:
    filing = FilingAggregate(
        accession=AccessionNumber.from_any("0001181431-05-056000"),
        primary_cik=Cik(109694),
        ciks=(Cik(109694),),
        form="4",
        filing_date="2005-09-15",
    )
    report = get_report_projection(filing)

    assert isinstance(report, OwnershipReport)
    assert report.form == "4"
    assert report.accession == "0001181431-05-056000"


def test_annual_form_projects_to_annual_report() -> None:
    filing = FilingAggregate(
        accession=AccessionNumber.from_any("0000320193-23-000106"),
        primary_cik=Cik(320193),
        ciks=(Cik(320193),),
        form="10-K",
        filing_date="2023-11-03",
    )
    report = get_report_projection(filing)

    assert isinstance(report, AnnualReport)
    assert isinstance(report, CompanyReport)


def test_quarterly_form_projects_to_quarterly_report() -> None:
    filing = FilingAggregate(
        accession=AccessionNumber.from_any("0000320193-23-000077"),
        primary_cik=Cik(320193),
        ciks=(Cik(320193),),
        form="10-Q",
        filing_date="2023-08-04",
    )
    report = get_report_projection(filing)

    assert isinstance(report, QuarterlyReport)
    assert isinstance(report, CompanyReport)


def test_current_form_projects_to_current_report() -> None:
    filing = FilingAggregate(
        accession=AccessionNumber.from_any("0000320193-23-000080"),
        primary_cik=Cik(320193),
        ciks=(Cik(320193),),
        form="8-K",
        filing_date="2023-09-12",
    )
    report = get_report_projection(filing)

    assert isinstance(report, CurrentReport)
    assert isinstance(report, CompanyReport)


def test_unknown_form_projects_to_generic_report() -> None:
    filing = FilingAggregate(
        accession=AccessionNumber.from_any("0000000000-00-000001"),
        primary_cik=Cik(1),
        ciks=(Cik(1),),
        form="UNKNOWN",
        filing_date="2024-01-01",
    )
    report = filing.as_report()

    assert isinstance(report, GenericReport)
