"""Period keys: the shared line-level period vocabulary."""

from __future__ import annotations

from edgar_sec.engine.tables.extraction.core.text.period_keys import (
    period_keys,
    priced_years,
    starts_with_period,
)


def test_priced_years_read_the_full_range() -> None:
    assert priced_years("fiscal 2024 and 2100") == ["2024", "2100"]
    assert priced_years("in 1899 and 1900") == ["1900"]


def test_period_keys_carry_a_post_2099_year() -> None:
    assert ("y", "2100") in period_keys("ended december 31, 2100")


def test_starts_with_period_opens_on_a_post_2099_year() -> None:
    assert starts_with_period("2100 | 100")
    assert not starts_with_period("1899 | 100")
