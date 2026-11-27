"""Section corpus banking: one specimen end to end from a local body."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from edgar_sec.tools.section_corpus.build import (
    _fetch_body,
    bank_specimen,
    prepare_jobs,
)
from tests.support.fixtures import fixture_path


class _RecordingClient:
    """Offline double capturing the archive URL _fetch_body builds."""

    def __init__(self) -> None:
        self.url = ""

    def get_bytes(self, url: str) -> bytes:
        self.url = url
        return b""


def test_fetch_body_consumes_the_job_cik() -> None:
    job = {
        "accession": "0001193125-12-106550",
        "document": "d310572dn30d.txt",
        "cik": 752372,
    }
    dashed = _RecordingClient()
    _fetch_body(job, dashed)  # type: ignore[arg-type]
    dashless = _RecordingClient()
    _fetch_body({**job, "accession": "000119312512106550"}, dashless)  # type: ignore[arg-type]
    assert dashed.url == dashless.url
    assert "/752372/000119312512106550/" in dashed.url


def test_fetch_body_without_a_job_cik_raises() -> None:
    job = {"accession": "0001193125-12-106550", "document": "d310572dn30d.txt"}
    with pytest.raises(ValueError, match="carries no cik"):
        _fetch_body(job, _RecordingClient())  # type: ignore[arg-type]


_IDX_HEADER = b"Description: Quarterly index\nLast Data Received:\n\n"
_IDX_ROW = (
    b"N-30D  Some Fund Inc  912057  2000-11-14  "
    b"Archives/edgar/data/912057/0000912057-00-051893.txt\n"
)


class _IdxClient:
    """Offline double serving one canned form.idx quarter."""

    def __init__(self) -> None:
        self.urls: list[str] = []

    def get_bytes(self, url: str) -> bytes:
        self.urls.append(url)
        return _IDX_HEADER + (_IDX_ROW if url.endswith("QTR3/form.idx") else b"")


def test_prepare_jobs_joins_the_registrant_cik_from_form_idx() -> None:
    jobs = [
        {"accession": "0000912057-00-051893", "document": "a.txt"},
        {"accession": "000091205700051893", "document": "a.txt"},
    ]
    client = _IdxClient()
    prepare_jobs(jobs, client)  # type: ignore[arg-type]
    assert [job["cik"] for job in jobs] == [912057, 912057]
    assert client.urls[0].endswith("/2000/QTR1/form.idx")


_JOB = {
    "slug": "control_18k",
    "form": "18-K/A",
    "accession": "0001104659-26-117215",
    "document": "tm2627716d1_18ka.htm",
    "era": "2026",
}


def test_bank_specimen_reproduces_the_committed_corpus_entry(
    tmp_path: Path,
) -> None:
    body = fixture_path(
        "document/form_18k/0001104659-26-117215__tm2627716d1_18ka.htm"
    ).read_bytes()
    record = bank_specimen(tmp_path, _JOB, body)

    corpus = fixture_path("engine/forms/sections/section_corpus")
    committed = next(
        e
        for e in json.loads((corpus / "index.json").read_text(encoding="utf-8"))
        if e["id"] == record["id"]
    )
    assert record["baseline"] == committed["baseline"]
    assert record["toc_span"] == committed["toc_span"]
    banked_text = (tmp_path / record["text"]).read_text(encoding="utf-8")
    committed_text = (corpus / committed["text"]).read_text(encoding="utf-8")
    assert banked_text == committed_text


def test_bank_specimen_writes_index_and_taxonomy(tmp_path: Path) -> None:
    body = fixture_path(
        "document/form_18k/0001104659-26-117215__tm2627716d1_18ka.htm"
    ).read_bytes()
    record = bank_specimen(tmp_path, _JOB, body)

    index = json.loads((tmp_path / "index.json").read_text(encoding="utf-8"))
    assert [e["id"] for e in index] == [record["id"]]
    taxonomies = json.loads((tmp_path / "taxonomies.json").read_text(encoding="utf-8"))
    assert taxonomies["control_18k"]
    assert record["expected"] == record["baseline"]
