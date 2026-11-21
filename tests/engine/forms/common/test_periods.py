"""Unit tests for engine common periods and amendment regexes."""

from edgar_sec.engine.forms.common.periods import (
    AMEND_DATE_CLEAN_RE,
    BOX5_SPLIT_RE,
    PERIOD_MATCH_RE,
)


def test_period_match():
    """Verify period extraction from header line."""
    text = "Statement for (Month/Day/Year): October 2023"
    match = PERIOD_MATCH_RE.search(text)
    assert match is not None
    assert "October 2023" in match.group(1)


def test_box5_split_and_amend_clean():
    """Verify amendment split and prefix cleanup."""
    assert bool(BOX5_SPLIT_RE.search("5. if amendment, date of original"))
    assert (
        AMEND_DATE_CLEAN_RE.sub("", "Date of Original: 01/15/2023").strip()
        == "01/15/2023"
    )
