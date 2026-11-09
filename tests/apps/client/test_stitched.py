"""Company stitched series: selection, assembly, and provenance."""

from __future__ import annotations

from edgar_sec.apps.client.entity import Company
from edgar_sec.apps.client.facade import Edgar
from edgar_sec.apps.client.models import FilingsResult
from edgar_sec.apps.client.stitched import expand_form_families
from edgar_sec.domain.document.aggregate import FilingAggregate
from edgar_sec.domain.identity import AccessionNumber, Cik
from edgar_sec.domain.submissions.models import EntityProfile
from edgar_sec.engine.xbrl.schema.models import FilingXbrl, LinkbaseBundle, XbrlFact

_CIK = 320193
_K22 = "0000320193-23-000050"
_K23 = "0000320193-24-000060"
_FY22 = ("2022-01-01", "2022-12-31")
_FY23 = ("2023-01-01", "2023-12-31")


def _aggregate(
    accession: str, *, filing_date: str, report_date: str
) -> FilingAggregate:
    return FilingAggregate(
        accession=AccessionNumber.from_any(accession),
        primary_cik=Cik(_CIK),
        ciks=(Cik(_CIK),),
        form="10-K",
        filing_date=filing_date,
        report_date=report_date,
    )


def _fact(accession: str, value: float, span: tuple[str, str]) -> XbrlFact:
    return XbrlFact(
        accession=AccessionNumber.from_any(accession),
        concept_qname="us-gaap:Revenues",
        value=value,
        unit="USD",
        period_type="duration",
        start_date=span[0],
        end_date=span[1],
    )


def _stub_company(monkeypatch, tmp_path) -> Company:
    """A Company whose filings and parse seams serve two 10-K filings."""
    first = _aggregate(_K22, filing_date="2023-03-01", report_date="2022-12-31")
    second = _aggregate(_K23, filing_date="2024-03-01", report_date="2023-12-31")
    parsed = {
        _K22: FilingXbrl(
            accession=first.accession,
            cik=first.primary_cik,
            facts=(_fact(_K22, 100.0, _FY22),),
            linkbases=LinkbaseBundle(),
        ),
        _K23: FilingXbrl(
            accession=second.accession,
            cik=second.primary_cik,
            facts=(_fact(_K23, 110.0, _FY22), _fact(_K23, 200.0, _FY23)),
            linkbases=LinkbaseBundle(),
        ),
    }
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
        items=(first, second),
    )
    monkeypatch.setattr(Company, "filings", lambda self, **kwargs: result)
    return Company(
        profile=EntityProfile(cik=Cik(_CIK), name="Series Co"),
        facade=Edgar(artifacts_root=tmp_path),
    )


def test_company_series_auto_selection_stitches(monkeypatch, tmp_path) -> None:
    company = _stub_company(monkeypatch, tmp_path)
    series = company.stitched_series("10-K")
    assert series is not None
    assert series.cik == "0000320193"
    assert series.accessions == (_K22, _K23)
    winner = series.value("us-gaap:Revenues", start_date=_FY22[0], end_date=_FY22[1])
    assert winner is not None
    assert (winner.value, winner.source_accession) == (110.0, _K23)
    assert [(item.value, item.superseded_by) for item in series.superseded] == [
        (100.0, _K23)
    ]
    current = series.value("us-gaap:Revenues", start_date=_FY23[0], end_date=_FY23[1])
    assert current is not None
    assert current.value == 200.0


def test_company_series_accession_override_selects_only_the_list(
    monkeypatch, tmp_path
) -> None:
    company = _stub_company(monkeypatch, tmp_path)
    series = company.stitched_series(accessions=[_K22])
    assert series is not None
    assert series.accessions == (_K22,)
    winner = series.value("us-gaap:Revenues", start_date=_FY22[0], end_date=_FY22[1])
    assert winner is not None
    assert winner.value == 100.0
    assert series.superseded == ()


def test_company_series_without_a_facade_is_none() -> None:
    company = Company(profile=EntityProfile(cik=Cik(_CIK), name="Series Co"))
    assert company.stitched_series() is None


def test_expand_form_families() -> None:
    assert expand_form_families(None) == ()
    assert expand_form_families("10-Q/A") == ("10-Q", "10-Q/A")
    assert expand_form_families(["10-K", "10-K/A"]) == ("10-K", "10-K/A")
