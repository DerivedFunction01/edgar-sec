"""Pins for the quarter-segment home (Wave 2B).
The ``YYYY/QTRn`` segment lives in ``domain.sec_urls``;
``domain.index_urls`` binds it for its index paths.
"""

from __future__ import annotations

import pytest

from edgar_sec.domain import index_urls, sec_urls


def test_binding_is_the_sec_urls_home() -> None:
    assert index_urls._index_quarter is sec_urls._feed_quarter


def test_quarter_verdicts() -> None:
    assert sec_urls._feed_quarter(2024, 2) == "2024/QTR2"
    assert sec_urls._feed_quarter(999, 1) == "0999/QTR1"
    assert index_urls._index_quarter(2025, 4) == "2025/QTR4"


def test_quarter_range_verdicts() -> None:
    with pytest.raises(ValueError):
        sec_urls._feed_quarter(2024, 0)
    with pytest.raises(ValueError):
        sec_urls._feed_quarter(2024, 5)
