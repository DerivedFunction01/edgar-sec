"""The single place an EDGAR URL is assembled; CIK padding and accession hyphens
are pinned so a caller-dependent difference cannot return.
"""

from __future__ import annotations

import pytest

from edgar_sec.domain.sec_urls import (
    SEC_ARCHIVE_BASE,
    SEC_SUBMISSIONS_BASE,
    archives_url,
    historical_submissions_url,
    normalize_cik,
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
