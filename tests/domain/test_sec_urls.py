"""The single place an EDGAR URL is assembled; CIK padding and accession hyphens
are pinned so a caller-dependent difference cannot return.
"""

from __future__ import annotations

import pytest

from edgar_sec.domain.sec_urls import (
    SEC_ARCHIVE_BASE,
    SEC_SUBMISSIONS_BASE,
    SEC_XBRL_API_BASE,
    archives_url,
    classify_sec_surface,
    companyconcept_url,
    companyfacts_url,
    frames_url,
    current_filings_url,
    daily_index_url,
    efts_search_url,
    full_index_url,
    historical_submissions_url,
    index_json_url_for,
    normalize_cik,
    structured_archive_url,
    structured_feed_url,
    submissions_bulk_url,
    submissions_url,
)


def test_base_prefixes_are_canonical() -> None:
    assert SEC_SUBMISSIONS_BASE == "https://data.sec.gov/submissions"
    assert SEC_ARCHIVE_BASE == "https://www.sec.gov/Archives/edgar/data"


@pytest.mark.parametrize("raw", ["320193", "0000320193", 320193, "1985", "20"])
def test_normalize_cik_always_pads_to_ten_digits(raw: str | int) -> None:
    padded = normalize_cik(raw)
    assert len(padded) == 10
    assert padded.startswith("0")
    assert int(padded) == int(str(raw))


def test_submissions_url_is_cik_padding_independent() -> None:
    expected = "https://data.sec.gov/submissions/CIK0000320193.json"
    assert submissions_url("320193") == expected
    assert submissions_url("0000320193") == expected
    assert submissions_url(320193) == expected


def test_submissions_url_keeps_a_longer_cik_intact() -> None:
    """Padding must not truncate a value that is already long enough."""
    assert normalize_cik("0000012345") == "0000012345"


def test_historical_submissions_url() -> None:
    assert (
        historical_submissions_url("CIK0000037996-submissions-001.json")
        == "https://data.sec.gov/submissions/CIK0000037996-submissions-001.json"
    )


def test_archives_url_unpads_cik_and_strips_hyphens() -> None:
    assert archives_url("0000320193", "0000320193-23-000106", "a.htm") == (
        "https://www.sec.gov/Archives/edgar/data/320193/000032019323000106/a.htm"
    )


def test_archives_url_ignores_padding_style_of_both_arguments() -> None:
    padded = archives_url("0000320193", "0000320193-23-000106", "a.htm")
    bare = archives_url("320193", "000032019323000106", "a.htm")
    assert padded == bare


def test_companyconcept_url_pads_cik_and_keeps_tag_verbatim() -> None:
    expected = (
        "https://data.sec.gov/api/xbrl/companyconcept/CIK0000320193/us-gaap/Assets.json"
    )
    assert SEC_XBRL_API_BASE == "https://data.sec.gov/api/xbrl"
    assert companyconcept_url("320193", "us-gaap", "Assets") == expected
    assert companyconcept_url(320193, "us-gaap", "Assets") == expected


def test_companyfacts_url_pads_cik() -> None:
    expected = "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json"
    assert companyfacts_url("320193") == expected
    assert companyfacts_url(320193) == expected


def test_frames_url_pins_taxonomy_tag_unit_period_shape() -> None:
    assert frames_url("us-gaap", "Assets", "USD", "CY2025Q4I") == (
        "https://data.sec.gov/api/xbrl/frames/us-gaap/Assets/USD/CY2025Q4I.json"
    )
    assert frames_url("us-gaap", "Revenues", "USD", "CY2025Q4") == (
        "https://data.sec.gov/api/xbrl/frames/us-gaap/Revenues/USD/CY2025Q4.json"
    )


def test_facts_family_urls_each_classify_to_their_own_surface() -> None:
    assert classify_sec_surface(companyconcept_url(320193, "us-gaap", "Assets")) == (
        "companyconcept"
    )
    assert classify_sec_surface(companyfacts_url(320193)) == "companyfacts"
    assert (
        classify_sec_surface(frames_url("us-gaap", "Assets", "USD", "CY2025Q4I"))
        == "frames"
    )


def test_bare_xbrl_api_path_classifies_as_no_facts_family_surface() -> None:
    assert classify_sec_surface("https://data.sec.gov/api/xbrl") is None
    assert classify_sec_surface("https://data.sec.gov/api/xbrl/") is None
    assert classify_sec_surface("https://data.sec.gov/api/xbrl/other/x") is None


def test_index_json_url_for_unhyphenates_accession() -> None:
    expected = (
        "https://www.sec.gov/Archives/edgar/data/320193/000032019323000106/index.json"
    )
    assert index_json_url_for("0000320193-23-000106", "0000320193") == expected
    assert index_json_url_for("000032019323000106", 320193) == expected


def test_current_filings_url_pins_the_getcurrent_atom_shape() -> None:
    assert current_filings_url() == (
        "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&output=atom"
    )
    assert current_filings_url(form="10-K", cik="320193", count=40, start=80) == (
        "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=10-K"
        "&CIK=320193&count=40&start=80&output=atom"
    )
    assert classify_sec_surface(current_filings_url()) == "current_filings"


@pytest.mark.parametrize(
    ("feed", "filename"),
    [
        ("usgaap", "usgaap.rss.xml"),
        ("risk_return", "xbrl-rr.rss.xml"),
        ("inline", "xbrl-inline.rss.xml"),
        ("all", "xbrlrss.all.xml"),
    ],
)
def test_structured_feed_url_names_each_live_feed(feed: str, filename: str) -> None:
    url = structured_feed_url(feed)
    assert url == f"https://www.sec.gov/Archives/edgar/{filename}"
    assert structured_feed_url(filename) == url
    assert classify_sec_surface(url) == "structured_disclosure_feeds"


def test_structured_feed_url_refuses_an_unknown_feed() -> None:
    with pytest.raises(ValueError):
        structured_feed_url("nope")


def test_structured_archive_url_pins_the_monthly_shape() -> None:
    url = structured_archive_url(2026, 3)
    assert url == "https://www.sec.gov/Archives/edgar/monthly/xbrlrss-2026-03.xml"
    assert classify_sec_surface(url) == "structured_disclosure_archives"
    with pytest.raises(ValueError):
        structured_archive_url(2026, 13)


def test_efts_search_url_is_the_bare_search_index_base() -> None:
    assert efts_search_url() == "https://efts.sec.gov/LATEST/search-index"
    assert classify_sec_surface(efts_search_url()) == "efts"


def test_submissions_bulk_url() -> None:
    assert submissions_bulk_url() == (
        "https://www.sec.gov/Archives/edgar/daily-index/bulkdata/submissions.zip"
    )
    assert classify_sec_surface(submissions_bulk_url()) == "submissions_bulk"


@pytest.mark.parametrize("flavour", ["master", "company", "form", "crawler", "xbrl"])
def test_full_index_url_pins_the_quarterly_shape(flavour: str) -> None:
    url = full_index_url(2024, 1, flavour)
    assert (
        url == f"https://www.sec.gov/Archives/edgar/full-index/2024/QTR1/{flavour}.idx"
    )
    assert classify_sec_surface(url) == "full_index"


def test_full_index_url_names_a_compressed_variant() -> None:
    url = full_index_url(2024, 1, "master", extension="gz")
    assert url == "https://www.sec.gov/Archives/edgar/full-index/2024/QTR1/master.gz"
    assert classify_sec_surface(url) == "full_index"


def test_full_index_url_refuses_unserved_shapes() -> None:
    with pytest.raises(ValueError):
        full_index_url(2024, 5, "master")
    with pytest.raises(ValueError):
        full_index_url(2024, 1, "nope")
    with pytest.raises(ValueError):
        full_index_url(2024, 1, "crawler", extension="gz")


@pytest.mark.parametrize("flavour", ["master", "company", "form", "crawler"])
def test_daily_index_url_pins_the_per_day_shape(flavour: str) -> None:
    url = daily_index_url("2026-11-06", flavour)
    assert url == (
        "https://www.sec.gov/Archives/edgar/daily-index/2026/QTR4/"
        f"{flavour}.20261106.idx"
    )
    assert classify_sec_surface(url) == "daily_index"


def test_daily_index_url_derives_the_quarter_from_the_day() -> None:
    assert daily_index_url("2024-02-13", "master") == (
        "https://www.sec.gov/Archives/edgar/daily-index/2024/QTR1/master.20240213.idx"
    )
    with pytest.raises(ValueError):
        daily_index_url("2026-11-06", "xbrl")
    with pytest.raises(ValueError):
        daily_index_url("not-a-date", "master")


def test_engine_builder_agrees_with_the_canonical_archive_shape() -> None:
    """build_archive_url must not assemble a different URL shape."""
    from edgar_sec.engine.submissions.helpers import build_archive_url

    url, reason = build_archive_url(
        "0000320193", "0000320193-23-000106", "aapl-20230930.htm"
    )
    assert url == archives_url(
        "0000320193", "0000320193-23-000106", "aapl-20230930.htm"
    )
    assert reason is None


def test_dataset_builders_pin_their_shapes_and_surfaces() -> None:
    from edgar_sec.domain.sec_urls import (
        bdc_dataset_url,
        bdc_report_url,
        mfrr_dataset_url,
        nmfp_dataset_url,
    )

    bdc = bdc_dataset_url("2025q1")
    assert bdc == (
        "https://www.sec.gov/files/datastandardsinnovation/data/"
        "business-development-company-bdc-data-sets/2025q1_bdc.zip"
    )
    assert classify_sec_surface(bdc) == "bdc_datasets"
    nmfp = nmfp_dataset_url("20220808-20220908")
    assert nmfp == (
        "https://www.sec.gov/files/dera/data/form-n-mfp-data-sets/"
        "20220808-20220908_nmfp.zip"
    )
    assert classify_sec_surface(nmfp) == "nmfp_datasets"
    mfrr = mfrr_dataset_url("2010q4")
    assert mfrr == (
        "https://www.sec.gov/files/dera/data/mutual-fund-prospectus-risk/"
        "return-summary-data-sets/2010q4_rr1.zip"
    )
    assert classify_sec_surface(mfrr) == "mfrr_datasets"
    report = bdc_report_url(2026)
    assert report == (
        "https://www.sec.gov/files/investment/data/other/"
        "business-development-company-report/business-development-company-2026.csv"
    )
    assert classify_sec_surface(report) == "bdc_report"


def test_dataset_builders_refuse_path_like_vintages() -> None:
    from edgar_sec.domain.sec_urls import bdc_dataset_url, bdc_report_url

    with pytest.raises(ValueError):
        bdc_dataset_url("../2025q1")
    with pytest.raises(ValueError):
        bdc_report_url(1999)
