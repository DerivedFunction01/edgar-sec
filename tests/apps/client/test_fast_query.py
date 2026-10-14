"""Tests for fast-path catalog query and client model ergonomics."""

from __future__ import annotations

import zipfile
from pathlib import Path
from unittest.mock import MagicMock

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from edgar_sec.apps.client.cache import DocumentCache
from edgar_sec.apps.client.facade import Edgar
from edgar_sec.apps.client.fast_query import query_catalog_fast
from edgar_sec.apps.client.models import FilingsResult
from edgar_sec.domain.document.aggregate import FilingAggregate
from edgar_sec.domain.forms.reports import CompanyReport
from edgar_sec.domain.identity import AccessionNumber, Cik


def test_filings_result_convenience_methods() -> None:
    f1 = FilingAggregate(
        accession=AccessionNumber.from_any("0000320193-21-000001"),
        primary_cik=Cik.from_raw(320193),
        ciks=(Cik.from_raw(320193),),
        form="10-K",
        filing_date="2021-10-28",
    )
    f2 = FilingAggregate(
        accession=AccessionNumber.from_any("0000320193-22-000002"),
        primary_cik=Cik.from_raw(320193),
        ciks=(Cik.from_raw(320193),),
        form="10-K",
        filing_date="2022-10-27",
    )
    f3 = FilingAggregate(
        accession=AccessionNumber.from_any("0000320193-23-000106"),
        primary_cik=Cik.from_raw(320193),
        ciks=(Cik.from_raw(320193),),
        form="8-K",
        filing_date="2023-11-03",
    )

    res = FilingsResult(
        run_id="fast-path",
        plan_id="fast-path",
        target_parquet_glob="",
        run_state_sqlite_path=Path("/tmp/state.sqlite"),
        artifacts_root=Path("/tmp"),
        items=(f1, f2, f3),
    )

    assert len(res) == 3
    assert res.first() == f1
    assert res.latest() == f3

    filtered_10k = res.filter(form="10-K")
    assert len(filtered_10k) == 2
    assert filtered_10k.latest() == f2

    filtered_date = res.filter(date="2021")
    assert len(filtered_date) == 1
    assert filtered_date.first() == f1


def test_filing_aggregate_raw_save_and_to_zip(tmp_path: Path) -> None:
    cache = DocumentCache(db_path=tmp_path / "cache.sqlite")
    content = b"<html>AAPL 10-K Content</html>"

    f = FilingAggregate(
        accession=AccessionNumber.from_any("0000320193-23-000106"),
        primary_cik=Cik.from_raw(320193),
        ciks=(Cik.from_raw(320193),),
        form="10-K",
        filing_date="2023-11-03",
        primary_document_path="aapl-20230930.htm",
        fetcher=lambda filing: content,
        cache_clearer=cache.clear,
    )

    assert f.raw() == content
    report = CompanyReport(filing=f)
    assert report.text() == "<html>AAPL 10-K Content</html>"

    saved = f.save(tmp_path / "saved.htm")
    assert saved.is_file()
    assert saved.read_bytes() == content

    zip_target = tmp_path / "filing.zip"
    f.to_zip(zip_target)
    assert zip_target.is_file()
    with zipfile.ZipFile(zip_target, "r") as zf:
        assert "0000320193-23-000106/aapl-20230930.htm" in zf.namelist()


def test_query_catalog_fast_with_mock_targets(tmp_path: Path) -> None:
    targets_dir = tmp_path / "filing_catalog" / "filing_targets"
    targets_dir.mkdir(parents=True, exist_ok=True)

    table = pa.Table.from_arrays(
        [
            pa.array(["0000320193-23-000106"]),
            pa.array([320193]),
            pa.array(["10-K"]),
            pa.array(["2023-11-03"]),
            pa.array(["2023-09-30"]),
            pa.array(["aapl-20230930.htm"]),
            pa.array(
                [
                    "https://www.sec.gov/Archives/edgar/data/320193/000032019323000106/aapl-20230930.htm"
                ]
            ),
        ],
        names=[
            "accession",
            "source_cik",
            "form",
            "filing_date",
            "report_date",
            "primary_document",
            "primary_doc_url",
        ],
    )
    pq.write_table(table, targets_dir / "part-00000.parquet")

    mock_client = MagicMock()
    mock_client.get_bytes.return_value = b"mock html payload"
    cache = DocumentCache(db_path=tmp_path / "test_docs.sqlite")

    result = query_catalog_fast(
        ciks=["320193"],
        forms="10-K",
        artifacts_root=tmp_path,
        cache=cache,
        http_client_factory=lambda: mock_client,
    )

    assert len(result) == 1
    filing = result.latest()
    assert filing is not None
    assert filing.accession.value == "0000320193-23-000106"
    assert filing.form == "10-K"

    raw_payload = filing.raw()
    assert raw_payload == b"mock html payload"
    mock_client.get_bytes.assert_called_once()

    cached_payload = filing.raw()
    assert cached_payload == b"mock html payload"
    assert mock_client.get_bytes.call_count == 1


def test_query_catalog_fast_on_the_fly_materialization(tmp_path: Path) -> None:
    import json

    mock_client = MagicMock()
    submissions_payload = {
        "cik": "0000320193",
        "name": "Apple Inc.",
        "filings": {
            "recent": {
                "accessionNumber": ["0000320193-23-000106"],
                "filingDate": ["2023-11-03"],
                "reportDate": ["2023-09-30"],
                "form": ["10-K"],
                "primaryDocument": ["aapl-20230930.htm"],
            }
        },
    }
    mock_client.get_bytes.return_value = json.dumps(submissions_payload).encode("utf-8")
    cache = DocumentCache(db_path=tmp_path / "cache.sqlite")

    empty_root = tmp_path / "empty_artifacts"
    result = query_catalog_fast(
        ciks=["320193"],
        forms="10-K",
        artifacts_root=empty_root,
        cache=cache,
        http_client_factory=lambda: mock_client,
    )

    assert len(result) == 1
    filing = result.latest()
    assert filing is not None
    assert filing.accession.raw == "0000320193-23-000106"
    assert filing.form == "10-K"
    assert filing.primary_document_path == "aapl-20230930.htm"
