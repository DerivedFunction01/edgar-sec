"""Tests for directory index.json parsing."""

from __future__ import annotations

import json

from edgar_sec.domain.document_inventory.models import (
    IndexPageInput,
    IndexParseFailure,
    IndexParseOutcome,
    ParsedIndexPage,
    UnrecognizedIndexPage,
)
from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.engine.index_pages.parser_json import (
    PARSER_FINGERPRINT,
    parse_json_index,
)

ACCESSION = AccessionNumber("0000123456-26-000016")
JSON_URL = (
    "https://www.sec.gov/Archives/edgar/data/123456/000012345626000016/index.json"
)


def _payload(items: list[dict]) -> bytes:
    return json.dumps({"directory": {"item": items}}).encode("utf-8")


def _parse(source: bytes) -> IndexParseOutcome:
    return parse_json_index(IndexPageInput(ACCESSION, JSON_URL, source))


def test_parses_entries_bundle_and_skips_index_artifacts() -> None:
    page = _parse(
        _payload(
            [
                {"name": "index.json", "last-modified": "2026-01-01", "size": "900"},
                {
                    "name": "0000123456-26-000016-index.html",
                    "last-modified": "2026-01-01",
                    "size": "5000",
                },
                {
                    "name": "0000123456-26-000016-index-headers.txt",
                    "last-modified": "2026-01-01",
                    "size": "300",
                },
                {
                    "name": "0000123456-26-000016-index-headers.html",
                    "last-modified": "2026-01-01",
                    "size": "300",
                },
                {
                    "name": "report.htm",
                    "last-modified": "2026-01-01",
                    "size": "12000",
                },
                {
                    "name": "data.xml",
                    "last-modified": "2026-01-01",
                    "size": "4000",
                },
                {
                    "name": "0000123456-26-000016.txt",
                    "last-modified": "2026-01-01",
                    "size": "20000",
                },
            ]
        )
    )

    assert PARSER_FINGERPRINT == "index-json-v1"
    assert isinstance(page, ParsedIndexPage)
    assert [entry.filename for entry in page.entries] == ["report.htm", "data.xml"]
    primary = page.entries[0]
    assert primary.table_kind == "document_format"
    assert primary.byte_size == 12000
    assert primary.sequence is None
    assert primary.document_type is None
    assert primary.description is None
    assert primary.archive_url == (
        "https://www.sec.gov/Archives/edgar/data/123456/000012345626000016/report.htm"
    )
    assert page.bundle_size == 20000
    assert page.bundle_url is not None and page.bundle_url.endswith(
        "0000123456-26-000016.txt"
    )
    assert page.diagnostics.items == ()


def test_malformed_json_is_a_parse_failure() -> None:
    page = _parse(b"{not json")

    assert isinstance(page, IndexParseFailure)
    assert page.diagnostic.code == "malformed_json"


def test_payload_without_directory_items_is_unrecognized() -> None:
    page = _parse(json.dumps({"other": {}}).encode("utf-8"))

    assert isinstance(page, UnrecognizedIndexPage)
    assert page.diagnostics.items[0].code == "unknown_table"


def test_invalid_size_is_flagged_and_entry_kept() -> None:
    page = _parse(
        _payload([{"name": "report.htm", "last-modified": "2026-01-01", "size": ""}])
    )

    assert isinstance(page, ParsedIndexPage)
    assert page.entries[0].byte_size is None
    assert page.diagnostics.items[0].code == "invalid_size"


def test_duplicate_filename_is_flagged() -> None:
    page = _parse(
        _payload(
            [
                {"name": "report.htm", "last-modified": "2026-01-01", "size": "10"},
                {"name": "REPORT.htm", "last-modified": "2026-01-01", "size": "10"},
            ]
        )
    )

    assert isinstance(page, ParsedIndexPage)
    assert page.diagnostics.items[0].code == "duplicate_filename"
