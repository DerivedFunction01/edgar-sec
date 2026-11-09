"""Lineage discovery: ref building and amendment-group selection."""

from __future__ import annotations

from edgar_sec.apps.client.lineages import filing_ref, lineage_group
from edgar_sec.domain.document.aggregate import FilingAggregate
from edgar_sec.domain.identity import AccessionNumber, Cik

_CIK = 320193
_ORIGINAL = "0000320193-24-000123"
_AMENDMENT = "0000320193-24-000130"
_OTHER_PERIOD = "0000320193-24-000140"


def _aggregate(
    accession: str,
    *,
    form: str = "10-Q",
    filing_date: str = "2024-05-01",
    report_date: str | None = "2024-03-31",
    cik: int = _CIK,
) -> FilingAggregate:
    return FilingAggregate(
        accession=AccessionNumber.from_any(accession),
        primary_cik=Cik(cik),
        ciks=(Cik(cik),),
        form=form,
        filing_date=filing_date,
        report_date=report_date,
    )


def test_filing_ref_needs_a_report_period() -> None:
    assert filing_ref(_aggregate(_ORIGINAL, report_date=None)) is None
    ref = filing_ref(_aggregate(_ORIGINAL))
    assert ref is not None
    assert ref.base_form == "10-Q"
    assert ref.report_period == "2024-03-31"


def test_group_orders_original_before_amendment() -> None:
    original = _aggregate(_ORIGINAL)
    amendment = _aggregate(_AMENDMENT, form="10-Q/A", filing_date="2024-06-15")
    group = lineage_group(amendment, [original, amendment])
    assert [member.accession.value for member in group] == [_ORIGINAL, _AMENDMENT]


def test_group_excludes_other_periods_forms_and_filers() -> None:
    original = _aggregate(_ORIGINAL)
    amendment = _aggregate(_AMENDMENT, form="10-Q/A", filing_date="2024-06-15")
    other_period = _aggregate(
        _OTHER_PERIOD, form="10-Q/A", filing_date="2024-06-15", report_date="2024-06-30"
    )
    other_form = _aggregate(
        "0000320193-24-000150", form="10-K/A", filing_date="2024-06-15"
    )
    other_filer = _aggregate(
        "0000000001-24-000150", form="10-Q/A", filing_date="2024-06-15", cik=1
    )
    group = lineage_group(
        original, [original, amendment, other_period, other_form, other_filer]
    )
    assert [member.accession.value for member in group] == [_ORIGINAL, _AMENDMENT]


def test_no_group_without_an_amendment() -> None:
    original = _aggregate(_ORIGINAL)
    assert lineage_group(original, [original]) == ()
    assert lineage_group(original, []) == ()


def test_no_group_without_a_report_period() -> None:
    filing = _aggregate(_ORIGINAL, report_date=None)
    amendment = _aggregate(_AMENDMENT, form="10-Q/A", report_date=None)
    assert lineage_group(filing, [filing, amendment]) == ()
