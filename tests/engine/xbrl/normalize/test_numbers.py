"""Number grammar: cardinals, ordinals, anchoring guards, ranges."""

from __future__ import annotations

from edgar_sec.engine.xbrl.normalize.numbers import (
    collapse_number_phrases,
    number_indexicals,
    parse_number_phrase,
)


def test_cardinal_composition() -> None:
    """Units, tens, and scales compose into single values."""
    assert parse_number_phrase(("Twenty", "One"), 0) == (21, 2)
    assert parse_number_phrase(("Ninety", "Nine"), 0) == (99, 2)
    assert parse_number_phrase(("One", "Hundred", "Five"), 0) == (105, 3)
    assert parse_number_phrase(("One", "Hundred", "Twenty", "Three"), 0) == (123, 4)
    assert parse_number_phrase(("Two", "Thousand", "Five"), 0) == (2005, 3)
    assert parse_number_phrase(("Twelve",), 0) == (12, 1)
    assert parse_number_phrase(("Stock",), 0) is None


def test_anchored_collapse() -> None:
    """Unit-anchored and bucket-anchored phrases collapse to NUM."""
    tokens, values, _ = collapse_number_phrases(("Due", "In", "Two", "Years"))
    assert tokens == ("Due", "In", "NUM", "Years")
    assert values == {2: 2}
    tokens, values, _ = collapse_number_phrases(("Rolling", "Year", "Two"))
    assert tokens == ("Rolling", "Year", "NUM")
    assert values == {2: 2}
    tokens, values, _ = collapse_number_phrases(("Maturity", "Year", "5", "Amount"))
    assert tokens == ("Maturity", "Year", "NUM", "Amount")
    assert values == {2: 5}


def test_unanchored_phrases_survive() -> None:
    """OneTime and trailing disambiguation digits are never collapsed."""
    tokens, values, _ = collapse_number_phrases(("One", "Time", "Charge"))
    assert tokens == ("One", "Time", "Charge")
    assert values == {}
    tokens, values, _ = collapse_number_phrases(
        ("Maturity", "Date", "Range", "End", "1")
    )
    assert tokens == ("Maturity", "Date", "Range", "End", "1")
    assert values == {}
    tokens, values, _ = collapse_number_phrases(("Threshold", "Trading", "Days", "1"))
    assert tokens == ("Threshold", "Trading", "Days", "1")
    assert values == {}


def test_tier_one_collapses() -> None:
    """Tier is an anchor word: the regulatory tier number is a value."""
    tokens, values, _ = collapse_number_phrases(
        ("Common", "Equity", "Tier", "One", "Ratio")
    )
    assert tokens == ("Common", "Equity", "Tier", "NUM", "Ratio")
    assert values == {3: 1}


def test_range_indexical_merges_through_pair() -> None:
    """NUM Through NUM renders as one num=<lo>..<hi> indexical."""
    tokens, values, _ = collapse_number_phrases(
        ("Maturities", "After", "Five", "Through", "Ten", "Years")
    )
    assert number_indexicals(tokens, values) == ("num=5..10",)
    tokens, values, _ = collapse_number_phrases(("Due", "In", "Two", "Years"))
    assert number_indexicals(tokens, values) == ("num=2",)


def test_ordinal_collapse_and_indexical() -> None:
    """Anchored ordinals collapse to NUM and render as ord=<v>."""
    tokens, values, ordinals = collapse_number_phrases(("Due", "In", "Fifth", "Year"))
    assert tokens == ("Due", "In", "NUM", "Year")
    assert values == {}
    assert ordinals == {2: 5}
    assert number_indexicals(tokens, values, ordinals) == ("ord=5",)


def test_ordinal_never_claims_third_party() -> None:
    """Unanchored ordinals survive: Third Party is a phrase, not a number."""
    tokens, values, ordinals = collapse_number_phrases(
        ("Guarantee", "By", "Third", "Party", "Amount")
    )
    assert tokens == ("Guarantee", "By", "Third", "Party", "Amount")
    assert values == {} and ordinals == {}
    tokens, values, ordinals = collapse_number_phrases(
        ("First", "Liquidation", "Right", "Amount")
    )
    assert tokens == ("First", "Liquidation", "Right", "Amount")
    assert ordinals == {}


def test_ordinal_range_merges_within_kind() -> None:
    """Ordinal ranges merge as ord=<lo>..<hi>; kinds never cross-merge."""
    tokens, values, ordinals = collapse_number_phrases(
        ("Due", "After", "First", "Through", "Fifth", "Year")
    )
    assert number_indexicals(tokens, values, ordinals) == ("ord=1..5",)


def test_level_anchor_collapses_hierarchy_numbers() -> None:
    """Level is an anchor word: fair-value hierarchy levels are values."""
    tokens, values, _ = collapse_number_phrases(
        ("Plan", "Assets", "Level", "3", "Reconciliation")
    )
    assert tokens == ("Plan", "Assets", "Level", "NUM", "Reconciliation")
    assert values == {3: 3}
    tokens, values, _ = collapse_number_phrases(("Level", "Three", "Inputs"))
    assert tokens == ("Level", "NUM", "Inputs")
    assert values == {1: 3}
