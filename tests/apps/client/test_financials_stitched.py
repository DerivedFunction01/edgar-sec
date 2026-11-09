"""Stitched financials surface: reported values plus narrowed derivations."""

from __future__ import annotations

from edgar_sec.apps.client.entity import Company
from edgar_sec.apps.client.facade import Edgar
from edgar_sec.apps.client.models import FilingsResult
from edgar_sec.domain.document.aggregate import FilingAggregate
from edgar_sec.domain.identity import AccessionNumber, Cik
from edgar_sec.domain.submissions.models import EntityProfile
from edgar_sec.engine.xbrl.schema.models import (
    ConceptDeclaration,
    FilingXbrl,
    LinkbaseBundle,
    XbrlFact,
)
from edgar_sec.engine.xbrl.solve.query import QueryStatus
from edgar_sec.engine.xbrl.solve.unaccumulate import NON_ADDITIVE_ITEM_TYPE

_CIK = 320193
_Q1 = "0000320193-23-000011"
_Q2 = "0000320193-23-000022"
_Q3 = "0000320193-23-000033"
_K = "0000320193-24-000044"
_REV = "us-gaap:Revenues"
_EPS = "us-gaap:EarningsPerShareBasic"
_Q1_SPAN = ("2023-01-01", "2023-03-31")
_YTD2_SPAN = ("2023-01-01", "2023-06-30")
_YTD3_SPAN = ("2023-01-01", "2023-09-30")
_FY_SPAN = ("2023-01-01", "2023-12-31")
_Q2_SPAN = ("2023-04-01", "2023-06-30")
_Q3_SPAN = ("2023-07-01", "2023-09-30")
_Q4_SPAN = ("2023-10-01", "2023-12-31")

_DECLARATIONS = (
    ConceptDeclaration(
        concept_qname=_REV, name="Revenues", item_type="xbrli:monetaryItemType"
    ),
    ConceptDeclaration(
        concept_qname=_EPS,
        name="EarningsPerShareBasic",
        item_type="dtr-types:perShareItemType",
    ),
)


def _aggregate(
    accession: str, *, form: str, filing_date: str, report_date: str
) -> FilingAggregate:
    return FilingAggregate(
        accession=AccessionNumber.from_any(accession),
        primary_cik=Cik(_CIK),
        ciks=(Cik(_CIK),),
        form=form,
        filing_date=filing_date,
        report_date=report_date,
    )


def _fact(
    accession: str, qname: str, value: float, span: tuple[str, str], unit: str
) -> XbrlFact:
    return XbrlFact(
        accession=AccessionNumber.from_any(accession),
        concept_qname=qname,
        value=value,
        unit=unit,
        period_type="duration",
        start_date=span[0],
        end_date=span[1],
    )


def _parsed(aggregate: FilingAggregate, facts) -> FilingXbrl:
    return FilingXbrl(
        accession=aggregate.accession,
        cik=aggregate.primary_cik,
        facts=tuple(facts),
        linkbases=LinkbaseBundle(declarations=_DECLARATIONS),
    )


def _stub_company(monkeypatch, tmp_path) -> Company:
    """A Company over a YTD-only year: revenue derives, EPS must not."""
    filings = [
        _aggregate(
            _Q1, form="10-Q", filing_date="2023-05-01", report_date="2023-03-31"
        ),
        _aggregate(
            _Q2, form="10-Q", filing_date="2023-08-01", report_date="2023-06-30"
        ),
        _aggregate(
            _Q3, form="10-Q", filing_date="2023-11-01", report_date="2023-09-30"
        ),
        _aggregate(_K, form="10-K", filing_date="2024-03-01", report_date="2023-12-31"),
    ]
    spans = (_Q1_SPAN, _YTD2_SPAN, _YTD3_SPAN, _FY_SPAN)
    amounts = {
        _Q1: (100.0, 1.0),
        _Q2: (300.0, 2.1),
        _Q3: (550.0, 3.0),
        _K: (800.0, 4.2),
    }
    parsed = {}
    for aggregate, span in zip(filings, spans):
        accession = aggregate.accession.value
        rev_amount, eps_amount = amounts[accession]
        parsed[accession] = _parsed(
            aggregate,
            [
                _fact(accession, _REV, rev_amount, span, "USD"),
                _fact(accession, _EPS, eps_amount, span, "USD/shares"),
            ],
        )
    monkeypatch.setattr(
        "edgar_sec.engine.xbrl.parsing.filing_parser.parse_filing_xbrl",
        lambda filing: parsed[filing.accession.value],
    )
    result = FilingsResult(
        run_id="test",
        plan_id="test",
        target_parquet_glob="",
        run_state_sqlite_path=tmp_path / "state.sqlite",
        artifacts_root=tmp_path,
        items=tuple(filings),
    )
    monkeypatch.setattr(Company, "filings", lambda self, **kwargs: result)
    return Company(
        profile=EntityProfile(cik=Cik(_CIK), name="Series Co"),
        facade=Edgar(artifacts_root=tmp_path),
    )


def test_surface_serves_derived_monetary_quarters(monkeypatch, tmp_path) -> None:
    company = _stub_company(monkeypatch, tmp_path)
    result = company.stitched_financials()
    assert result is not None
    assert result.accessions == (_Q1, _Q2, _Q3, _K)
    q2 = result.value(_REV, start_date=_Q2_SPAN[0], end_date=_Q2_SPAN[1])
    assert q2 is not None
    assert q2.value == 200.0
    assert q2.status == QueryStatus.DERIVED
    assert [item.accession for item in q2.derivation_inputs] == [_Q1, _Q2]
    q4 = result.value(_REV, start_date=_Q4_SPAN[0], end_date=_Q4_SPAN[1])
    assert q4 is not None and q4.value == 250.0
    served = {(item.start_date, item.end_date) for item in result.values(_REV)}
    assert served == {
        _Q1_SPAN,
        _YTD2_SPAN,
        _YTD3_SPAN,
        _FY_SPAN,
        _Q2_SPAN,
        _Q3_SPAN,
        _Q4_SPAN,
    }


def test_surface_refuses_per_share_derivations(monkeypatch, tmp_path) -> None:
    company = _stub_company(monkeypatch, tmp_path)
    result = company.stitched_financials()
    assert result is not None
    assert result.value(_EPS, start_date=_Q2_SPAN[0], end_date=_Q2_SPAN[1]) is None
    served = {(item.start_date, item.end_date) for item in result.values(_EPS)}
    assert served == {_Q1_SPAN, _YTD2_SPAN, _YTD3_SPAN, _FY_SPAN}
    eps_refusals = [item for item in result.refusals if item.concept_qname == _EPS]
    assert len(eps_refusals) == 3
    assert {item.reason for item in eps_refusals} == {NON_ADDITIVE_ITEM_TYPE}


def test_surface_accession_override_narrows_the_set(monkeypatch, tmp_path) -> None:
    company = _stub_company(monkeypatch, tmp_path)
    result = company.stitched_financials(accessions=[_Q1, _Q2])
    assert result is not None
    assert result.accessions == (_Q1, _Q2)
    q2 = result.value(_REV, start_date=_Q2_SPAN[0], end_date=_Q2_SPAN[1])
    assert q2 is not None and q2.value == 200.0
    assert result.value(_REV, start_date=_Q3_SPAN[0], end_date=_Q3_SPAN[1]) is None


def test_surface_without_a_facade_is_none() -> None:
    company = Company(profile=EntityProfile(cik=Cik(_CIK), name="Series Co"))
    assert company.stitched_financials() is None
