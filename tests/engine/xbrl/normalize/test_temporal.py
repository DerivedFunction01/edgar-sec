"""Unit tests for the interval-valued temporal facet."""

from edgar_sec.engine.xbrl.normalize.temporal import (
    BUCKET,
    RANGE,
    WINDOW,
    TemporalInterval,
    derive_horizon,
    extract_temporal,
)


def test_window_within_one_year() -> None:
    """A within/next span is a cumulative (0, N] window."""
    iv = extract_temporal(("Due", "Within", "NUM", "Year"), {2: 1}, {})
    assert iv == TemporalInterval(0, 12, WINDOW)
    assert derive_horizon(iv) == "M_CURRENT"


def test_ordinal_year_bucket() -> None:
    """An ordinal year is the year-k bucket ((k-1)*12, k*12]."""
    iv = extract_temporal(("In", "NUM", "Year"), {}, {1: 3})
    assert iv == TemporalInterval(24, 36, BUCKET)
    assert derive_horizon(iv) == "M_NONCURRENT"


def test_cardinal_year_bucket_reading() -> None:
    """In/DueIn + cardinal year k >= 2 reads as the year-k bucket (89/0 rule)."""
    iv = extract_temporal(("Receivable", "In", "NUM", "Years"), {2: 5}, {})
    assert iv == TemporalInterval(48, 60, BUCKET)


def test_through_range() -> None:
    """Two unit-anchored cardinals linked by Through form a range."""
    iv = extract_temporal(
        ("After", "NUM", "Years", "Through", "NUM", "Years"), {1: 5, 4: 10}, {}
    )
    assert iv == TemporalInterval(60, 120, RANGE)
    assert derive_horizon(iv) == "M_NONCURRENT"


def test_after_window_is_open_ended() -> None:
    """An after span is (N, infinity) and derives only the noncurrent side."""
    iv = extract_temporal(("Maturities", "After", "NUM", "Years"), {2: 10}, {})
    assert iv == TemporalInterval(120, None, WINDOW)
    assert derive_horizon(iv) == "M_NONCURRENT"
    short = extract_temporal(("Due", "After", "NUM", "Months"), {2: 6}, {})
    assert derive_horizon(short) is None


def test_straddling_window_derives_nothing() -> None:
    """A window crossing the one-year line derives no horizon."""
    iv = extract_temporal(("Due", "Within", "NUM", "Years"), {2: 2}, {})
    assert iv == TemporalInterval(0, 24, WINDOW)
    assert derive_horizon(iv) is None


def test_no_number_no_interval() -> None:
    """Names without anchored numbers carry no temporal facet."""
    assert extract_temporal(("Assets",), {}, {}) is None
    assert derive_horizon(None) is None
