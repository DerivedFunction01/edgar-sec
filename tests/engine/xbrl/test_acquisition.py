"""Tests for high-throughput cohort linkbase acquisition pipeline."""

from pathlib import Path

from edgar_sec.domain.sec_urls import index_url_for
from edgar_sec.engine.xbrl.acquisition import CohortAcquisitionPipeline
from edgar_sec.engine.xbrl.cohort import load_seed_cohort
from edgar_sec.engine.xbrl.discovery import LinkbaseType
from edgar_sec.engine.xbrl.storage import read_linkbase_parquet
from tests.support import FakeSession, build_test_http, fixture_path


def test_acquire_filing_offline(tmp_path: Path) -> None:
    """Verify single filing acquisition and XML download using FakeSession."""
    cohort = load_seed_cohort(fixture_path("xbrl/seed_cohort.json"))
    filing = cohort[0]
    expected_url = index_url_for(filing.accession, filing.cik)
    html_bytes = fixture_path("xbrl/msft_index_page.html").read_bytes()

    session = FakeSession()
    session.register_bytes(expected_url, html_bytes)
    # Register mock bytes for discovered calculation linkbase
    for lb_url in [
        "https://www.sec.gov/Archives/edgar/data/789019/000095017024087843/msft-20240630_cal.xml",
        "https://www.sec.gov/Archives/edgar/data/789019/000095017024087843/msft-20240630_lab.xml",
    ]:
        session.register_bytes(lb_url, b"<xml>mock</xml>")

    client = build_test_http(session)
    pipeline = CohortAcquisitionPipeline(
        client=client,
        cache_dir=tmp_path / "cache",
        max_workers=1,
    )

    result = pipeline.acquire_filing(filing, download_xml=True)
    assert result.success
    assert len(result.linkbases) > 0
    assert any(lb.linkbase_type == LinkbaseType.CALCULATION for lb in result.linkbases)
    assert len(result.downloaded_paths) > 0


def test_acquire_cohort_offline_to_parquet(tmp_path: Path) -> None:
    """Verify cohort acquisition writing linkbase inventory to Parquet."""
    cohort = load_seed_cohort(fixture_path("xbrl/seed_cohort.json"))
    filings = cohort[:2]
    html_bytes = fixture_path("xbrl/msft_index_page.html").read_bytes()

    session = FakeSession()
    for f in filings:
        session.register_bytes(index_url_for(f.accession, f.cik), html_bytes)

    client = build_test_http(session)
    pipeline = CohortAcquisitionPipeline(client=client, max_workers=2)
    out_parquet = tmp_path / "linkbases.parquet"

    results = pipeline.acquire_cohort(
        filings, download_xml=False, output_parquet=out_parquet
    )
    assert len(results) == 2
    assert all(r.success for r in results)
    assert out_parquet.exists()
    table = read_linkbase_parquet(out_parquet)
    assert table.num_rows > 0


def test_acquire_filing_error_handling() -> None:
    """Verify clean handling of HTTP error during filing acquisition."""
    cohort = load_seed_cohort(fixture_path("xbrl/seed_cohort.json"))
    filing = cohort[0]

    session = FakeSession()  # No registered URLs will 404/raise
    client = build_test_http(session)
    pipeline = CohortAcquisitionPipeline(client=client)

    result = pipeline.acquire_filing(filing)
    assert not result.success
    assert result.error is not None
