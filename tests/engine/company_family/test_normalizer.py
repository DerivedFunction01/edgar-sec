"""Tests for company-name normalization.

`TRADEMARK_RE` is built through the regex DSL rather than written by hand, and
that is exactly the sort of change whose failure is silent: a branch-ordering
mistake still compiles and still matches, just the wrong things. These tests pin
the observable behaviour of the pattern and of the pipeline that consumes it.
"""

from __future__ import annotations

import pytest

from edgar_sec.engine.company_family.normalizer import (
    TRADEMARK_RE,
    normalize_name,
    post_normalize,
)


@pytest.mark.parametrize("marker", ["(R)", "(TM)", "(SM)", "(C)", "(tm)", "(sm)"])
def test_trademark_pattern_matches_bare_markers(marker: str) -> None:
    assert TRADEMARK_RE.search(marker)


@pytest.mark.parametrize(
    "text",
    [
        "(Inc)",  # not a trademark marker
        "(Registrant)",  # a real parenthetical
        "()",  # empty
    ],
)
def test_trademark_pattern_ignores_non_markers(text: str) -> None:
    assert TRADEMARK_RE.search(text) is None


def test_trademark_marker_is_stripped_from_the_name() -> None:
    # "holdings" singularises via PLURAL_MAP, so the plural is not the assertion
    # under test; the marker being gone is.
    assert normalize_name("ACME (R) Holdings") == ["acme", "holding"]


def test_trademark_marker_does_not_change_the_surrounding_tokens() -> None:
    with_marker = normalize_name("ACME (R) Holdings")
    without = normalize_name("ACME Holdings")
    assert with_marker == without


def test_trademark_marker_does_not_eat_a_longer_parenthetical() -> None:
    """(Inc) shares the leading '(' but must survive; only bare markers go."""
    assert "inc" in normalize_name("ACME (Inc) Holdings")


def test_abbreviation_expands() -> None:
    assert normalize_name("International Business Machines") == [
        "international",
        "business",
        "machines",
    ]


def test_empty_name_yields_no_tokens() -> None:
    assert normalize_name("") == []
    assert normalize_name("   ") == []


def test_post_normalize_collapses_series_numbers() -> None:
    collapsed = post_normalize(["acme", "2011", "c", "5"])
    assert "2011" not in collapsed
    assert "c" not in collapsed
