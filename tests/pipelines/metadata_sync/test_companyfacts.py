"""Companyfacts bulk leg: planning, normalization keying, and the download."""

from __future__ import annotations

import io
import json
import zipfile as zipfile_module
from pathlib import Path

import pyarrow as pa
import pytest

from edgar_sec.domain.sec_urls import companyfacts_bulk_url
from edgar_sec.infra.storage.bulk_archive import MEMBER_INDEX_SCHEMA
from edgar_sec.pipelines.metadata_sync.companyfacts import (
    COMPANYFACTS_BULK_SOURCE_ID,
    CompanyFactsArchive,
    member_fingerprint,
    normalize_member,
    plan_members,
)
from tests.support import load_fixture


def _index(rows: list[tuple[str, int]]) -> pa.Table:
    return pa.table(
        {
            "member_name": [name for name, _crc in rows],
            "crc32": [crc for _name, crc in rows],
            "compressed_size": [10] * len(rows),
            "uncompressed_size": [20] * len(rows),
            "header_offset": [0] * len(rows),
        },
        schema=MEMBER_INDEX_SCHEMA,
    )


def test_plan_members_keys_plans_by_cik_and_crc() -> None:
    plans = plan_members(
        _index(
            [
                ("CIK0000320193.json", 111),
                ("CIK0000000020.json", 222),
                ("notes.txt", 333),
            ]
        )
    )

    assert [plan.cik_padded for plan in plans] == ["0000000020", "0000320193"]
    assert plans[1].cik == 320193
    assert plans[1].crc32 == 111
    assert plans[1].fingerprint == member_fingerprint("0000320193", 111)
    assert plans[0].fingerprint != plans[1].fingerprint


def test_normalize_member_maps_the_fixture_document_field_for_field() -> None:
    payload = load_fixture("companyfacts_multi.json")
    entity_name, table = normalize_member(
        "0000320193", json.dumps(payload).encode("utf-8")
    )

    assert entity_name == "Apple Inc."
    rows = table.to_pylist()
    assets = [
        row for row in rows if row["taxonomy"] == "us-gaap" and row["tag"] == "Assets"
    ]
    assert len(assets) == 2
    newest = max(assets, key=lambda row: row["end"])
    assert newest["cik"] == 320193
    assert newest["unit"] == "USD"
    assert newest["end"] == "2024-09-28"
    assert newest["start"] == ""
    assert newest["accession"] == "0000320193-24-000123"
    assert newest["form"] == "10-K"
    assert newest["filed"] == "2024-11-01"
    assert newest["fiscal_year"] == 2024
    assert newest["fiscal_period"] == "FY"
    assert newest["frame"] == "CY2024Q3I"
    assert newest["value"] == 364980000000.0
    keys = {
        (
            row["cik"],
            row["taxonomy"],
            row["tag"],
            row["unit"],
            row["end"],
            row["accession"],
        )
        for row in rows
    }
    assert len(keys) == len(rows)


def test_normalize_member_skips_non_numeric_points_and_empty_documents() -> None:
    payload = {
        "entityName": "Sparse Co",
        "facts": {
            "us-gaap": {
                "Assets": {
                    "units": {
                        "USD": [
                            {"val": True, "end": "2024-01-01", "accn": "a1"},
                            {"val": "x", "end": "2024-01-01", "accn": "a2"},
                            {"val": 7, "end": "2024-01-01", "accn": "a3"},
                        ]
                    }
                }
            }
        },
    }
    _name, table = normalize_member("0000000020", json.dumps(payload).encode())
    rows = table.to_pylist()
    assert len(rows) == 1
    assert rows[0]["accession"] == "a3"
    assert rows[0]["value"] == 7.0
    assert rows[0]["fiscal_year"] is None

    _name, empty = normalize_member("0000000020", b"{}")
    assert len(empty) == 0


def test_normalize_member_rejects_a_non_object_member() -> None:
    with pytest.raises(ValueError, match="not a JSON object"):
        normalize_member("0000000020", b"[1, 2]")
    with pytest.raises(ValueError, match="not JSON"):
        normalize_member("0000000020", b"not json")


class _StreamingHttp:
    """Fake transport honoring the real ``stream_to_file`` call shape."""

    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.calls: list[dict] = []

    def stream_to_file(
        self, url, destination, *, max_response_bytes, validate_redirect
    ):
        from edgar_sec.foundation.hashing import sha256_bytes
        from edgar_sec.infra.sec_http.streaming import StreamedResponse

        validate_redirect(url)
        Path(destination).write_bytes(self.payload)
        self.calls.append({"url": url, "max_response_bytes": max_response_bytes})
        return StreamedResponse(
            status_code=200,
            requested_url=url,
            final_url=url,
            sha256=sha256_bytes(self.payload),
            byte_size=len(self.payload),
            content_type="application/zip",
            content_encoding=None,
            path=Path(destination),
        )


def _archive_bytes(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile_module.ZipFile(buffer, "w") as archive:
        for name, payload in members.items():
            archive.writestr(name, payload)
    return buffer.getvalue()


def test_download_stores_under_the_companyfacts_source_id(tmp_path: Path) -> None:
    from edgar_sec.infra.storage.bulk_archive import BulkArchiveStore

    members = {"CIK0000000020.json": b'{"entityName": "Co", "facts": {}}'}
    http = _StreamingHttp(_archive_bytes(members))
    store = BulkArchiveStore(tmp_path / "store")

    archive = CompanyFactsArchive.download(http, store, max_bytes=10_000_000)

    assert http.calls[0]["url"] == companyfacts_bulk_url()
    assert http.calls[0]["max_response_bytes"] == 10_000_000
    stored = store.open(COMPANYFACTS_BULK_SOURCE_ID)
    assert stored is not None
    assert stored.sha256 == archive.archive_sha256
    assert archive.read_member("CIK0000000020.json") == members["CIK0000000020.json"]
    assert archive.read_member("CIK0000009999.json") is None
    archive.close()


def test_download_redirect_validator_rejects_leaving_the_xbrl_directory() -> None:
    from edgar_sec.pipelines.metadata_sync.companyfacts import (
        _validate_companyfacts_redirect,
    )

    _validate_companyfacts_redirect(companyfacts_bulk_url())
    with pytest.raises(ValueError):
        _validate_companyfacts_redirect(
            "https://www.sec.gov/Archives/edgar/daily-index/bulkdata/submissions.zip"
        )
    with pytest.raises(ValueError):
        _validate_companyfacts_redirect("https://example.com/x/companyfacts.zip")
