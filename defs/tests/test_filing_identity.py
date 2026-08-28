"""Contract tests for canonical filing identity primitives."""

import pytest

from defs.filing_identity import (
    ArchiveUrlParts,
    accession_hyphenated,
    archive_url_for,
    document_locator_key,
    filing_year,
    fiscal_year,
    is_amendment_form,
    normalize_accession,
    occurrence_id,
    parse_archive_url,
)


def test_normalize_accession_accepts_full_hyphenated_form():
    assert normalize_accession("0000006201-26-000014") == "000000620126000014"
    assert normalize_accession("0000037996-26-000039") == "000003799626000039"


def test_normalize_accession_zero_pads_short_components():
    assert normalize_accession("80255-10-000212") == "000008025510000212"
    assert normalize_accession("6201-26-14") == "000000620126000014"


def test_normalize_accession_accepts_canonical_digits_and_strips_whitespace():
    assert normalize_accession("000000620126000014") == "000000620126000014"
    assert normalize_accession(" 0000006201-26-000014 ") == "000000620126000014"


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "",
        "   ",
        "not-an-accession",
        "0000006201-26",  # two components
        "0000006201-260-000014",  # year component too long
        "0000006201-26-0000145",  # sequence component too long
        "00000062012600001",  # 17 digits
        "0000006201260000145",  # 19 digits
        "000000620X-26-000014",  # non-numeric component
    ],
)
def test_normalize_accession_rejects_ambiguous_values(raw):
    assert normalize_accession(raw) is None


def test_accession_hyphenated_is_derived_display_form():
    assert accession_hyphenated("000000620126000014") == "0000006201-26-000014"
    assert accession_hyphenated("000008025510000212") == "0000080255-10-000212"


def test_accession_hyphenated_rejects_non_canonical_input():
    with pytest.raises(ValueError):
        accession_hyphenated("0000006201-26-000014")
    with pytest.raises(ValueError):
        accession_hyphenated("12035777")


def test_parse_archive_url_handles_both_aal_alias_prefixes():
    for cik in ("4515", "6201"):
        parts = parse_archive_url(
            f"https://www.sec.gov/Archives/edgar/data/{cik}/000000620126000014/aal-20251231.htm"
        )
        assert parts == ArchiveUrlParts(
            url=f"https://www.sec.gov/Archives/edgar/data/{cik}/000000620126000014/aal-20251231.htm",
            archive_cik=cik,
            accession="000000620126000014",
            document_path="aal-20251231.htm",
        )


def test_parse_archive_url_keeps_nested_document_path_and_scheme():
    parts = parse_archive_url(
        "http://www.sec.gov/Archives/edgar/data/1551964/999999999512002915/xslEFFECTX01/primary_doc.xml"
    )
    assert parts is not None
    assert parts.archive_cik == "1551964"
    assert parts.accession == "999999999512002915"
    assert parts.document_path == "xslEFFECTX01/primary_doc.xml"


def test_parse_archive_url_normalizes_dashed_accession_segment():
    parts = parse_archive_url(
        "https://www.sec.gov/Archives/edgar/data/6201/0000006201-26-000014/aal-20251231.htm"
    )
    assert parts is not None
    assert parts.accession == "000000620126000014"


@pytest.mark.parametrize(
    "url",
    [
        None,
        "",
        "https://data.sec.gov/submissions/CIK0000006201.json",
        "https://www.sec.gov/Archives/edgar/data/6201/000000620126000014",
        "https://www.sec.gov/Archives/edgar/data/6201/000000620126000014/",
        "https://evil.gov/Archives/edgar/data/6201/000000620126000014/a.htm",
        "https://www.sec.gov/Archives/edgar/data/6201/short/a.htm",
    ],
)
def test_parse_archive_url_rejects_non_document_urls(url):
    assert parse_archive_url(url) is None


def test_archive_url_for_matches_observed_unpadded_cik_form():
    assert archive_url_for("0000006201", "000000620126000014", "aal-20251231.htm") == (
        "https://www.sec.gov/Archives/edgar/data/6201/000000620126000014/aal-20251231.htm"
    )
    assert archive_url_for("6201", "000000620126000014", "aal-20251231.htm") == (
        "https://www.sec.gov/Archives/edgar/data/6201/000000620126000014/aal-20251231.htm"
    )


def test_archive_url_for_round_trips_through_parse():
    url = archive_url_for("0001086364", "000108636410008819", "ktroninternat012910.txt")
    parts = parse_archive_url(url)
    assert parts is not None
    assert parts.archive_cik == "1086364"
    assert parts.accession == "000108636410008819"
    assert parts.document_path == "ktroninternat012910.txt"


@pytest.mark.parametrize(
    "cik,accession,path",
    [
        ("ABC", "000000620126000014", "a.htm"),
        ("6201", "6201-26-14", "a.htm"),
        ("6201", "000000620126000014", ""),
        ("6201", "000000620126000014", "   "),
    ],
)
def test_archive_url_for_rejects_invalid_components(cik, accession, path):
    with pytest.raises(ValueError):
        archive_url_for(cik, accession, path)


def test_occurrence_id_separates_alias_source_ciks_but_shares_locator():
    source_a = occurrence_id("4515", "0000006201-26-000014", "aal-20251231.htm")
    source_b = occurrence_id("6201", "000000620126000014", "aal-20251231.htm")
    assert source_a != source_b
    assert document_locator_key("0000006201-26-000014", "aal-20251231.htm") == (
        document_locator_key("000000620126000014", "aal-20251231.htm")
    )


def test_occurrence_id_is_stable_and_treats_missing_path_as_empty():
    base = occurrence_id("4515", "000000620126000014", "aal-20251231.htm")
    assert base == occurrence_id("4515", "000000620126000014", "aal-20251231.htm")
    assert base != occurrence_id("4515", "000000620126000014", None)
    assert occurrence_id("4515", "000000620126000014", None) == occurrence_id(
        "4515", "000000620126000014", ""
    )


def test_occurrence_id_changes_with_document_path():
    assert occurrence_id("4515", "000000620126000014", "aal-20251231.htm") != (
        occurrence_id("4515", "000000620126000014", "aal-20251231a.htm")
    )


def test_occurrence_id_rejects_missing_source_cik_or_bad_accession():
    with pytest.raises(ValueError):
        occurrence_id("", "000000620126000014", "a.htm")
    with pytest.raises(ValueError):
        occurrence_id("4515", "nope", "a.htm")


def test_document_locator_key_differs_when_document_path_differs():
    assert document_locator_key("000000620126000014", "aal-20251231.htm") != (
        document_locator_key("000000620126000014", "aal-20251231a.htm")
    )
    assert document_locator_key("000000620126000014", "aal-20251231.htm") != (
        document_locator_key("000000620126000015", "aal-20251231.htm")
    )


@pytest.mark.parametrize(
    "value,expected",
    [
        ("2026-02-05", "2026"),
        ("2026-02-05T18:04:21.431Z", "2026"),  # ISO datetime prefix is unambiguous
        ("1999-12-31", "1999"),
        ("20260205", None),
        ("", None),
        (None, None),
        ("unknown", None),
    ],
)
def test_filing_year_extracts_leading_iso_year(value, expected):
    assert filing_year(value) == expected


def test_fiscal_year_matches_report_date_derivation():
    assert fiscal_year("2025-12-31") == "2025"
    assert fiscal_year(None) is None


@pytest.mark.parametrize(
    "form,expected",
    [
        ("10-K", False),
        ("10-K/A", True),
        ("10-K/a", True),
        (" 10-Q/A ", True),
        ("8-K", False),
        ("", False),
        (None, False),
    ],
)
def test_is_amendment_form(form, expected):
    assert is_amendment_form(form) is expected
