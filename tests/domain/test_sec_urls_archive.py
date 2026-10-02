"""Tests for the EDGAR archive URL protocol facts."""

from __future__ import annotations

import pytest

from edgar_sec.domain.sec_urls import (
    accession_hyphenated,
    archives_url,
    full_submission_url_for,
    normalize_accession,
    parse_archive_url,
)

ARCHIVE_URL = (
    "https://www.sec.gov/Archives/edgar/data/320193/000032019320000096/"
    "0000320193-20-000096.htm"
)


def test_archives_url_uses_unpadded_cik_and_unhyphenated_accession() -> None:
    url = archives_url(320193, "0000320193-20-000096", "0000320193-20-000096.htm")
    assert url == ARCHIVE_URL


def test_archives_url_accepts_padded_cik() -> None:
    url = archives_url("0000320193", "000032019320000096", "0000320193-20-000096.htm")
    assert url == ARCHIVE_URL


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("0000320193-20-000096", "000032019320000096"),
        ("000032019320000096", "000032019320000096"),
        ("  0000320193-20-000096  ", "000032019320000096"),
    ],
)
def test_normalize_accession(raw: str, expected: str) -> None:
    assert normalize_accession(raw) == expected


@pytest.mark.parametrize("raw", ["", None, "abc", "123", "1" * 19])
def test_normalize_accession_rejects_junk(raw: str | None) -> None:
    assert normalize_accession(raw) is None


def test_accession_hyphenated_round_trip() -> None:
    assert accession_hyphenated("000032019320000096") == "0000320193-20-000096"
    assert normalize_accession(accession_hyphenated("000032019320000096")) == (
        "000032019320000096"
    )


def test_accession_hyphenated_rejects_junk() -> None:
    with pytest.raises(ValueError):
        accession_hyphenated("not-an-accession")


def test_parse_archive_url_extracts_components() -> None:
    parts = parse_archive_url(ARCHIVE_URL)
    assert parts is not None
    assert parts.archive_cik == "320193"
    assert parts.accession == "000032019320000096"
    assert parts.document_path == "0000320193-20-000096.htm"
    assert parts.url == ARCHIVE_URL


def test_parse_archive_url_keeps_nested_document_paths() -> None:
    url = (
        "https://www.sec.gov/Archives/edgar/data/320193/000032019320000096/"
        "xslF345X02/doc3.xml"
    )
    parts = parse_archive_url(url)
    assert parts is not None
    assert parts.document_path == "xslF345X02/doc3.xml"


@pytest.mark.parametrize(
    "url",
    [
        None,
        "",
        "https://example.com/not/an/archive",
        "https://www.sec.gov/Archives/edgar/data/320193",
        "https://www.sec.gov/Archives/edgar/data/320193/000032019320000096/",
    ],
)
def test_parse_archive_url_rejects_non_archive_urls(url: str | None) -> None:
    assert parse_archive_url(url) is None


def test_full_submission_url_for() -> None:
    assert full_submission_url_for("320193", "0000320193-20-000096") == (
        "https://www.sec.gov/Archives/edgar/data/320193/000032019320000096/"
        "0000320193-20-000096.txt"
    )


def test_full_submission_url_rejects_a_bad_accession() -> None:
    with pytest.raises(ValueError):
        full_submission_url_for("320193", "nope")
