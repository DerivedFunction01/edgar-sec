"""Unit tests for regex builder utilities."""

from enum import Enum

from edgar_sec.foundation.regex.builder import (
    add_restrictions,
    build_alternation,
    build_compound,
    build_regex,
    plural,
    to_list,
)


class SampleEnum(Enum):
    ALPHA = "alpha"
    BETA = "beta"


def test_to_list_flattening() -> None:
    assert to_list(None) == []
    assert to_list("test") == ["test"]
    assert to_list(SampleEnum.ALPHA) == ["alpha"]
    assert to_list(["a", ["b", ("c", SampleEnum.BETA)]]) == ["a", "b", "c", "beta"]


def test_build_alternation_ordering() -> None:
    # Longest words first
    result = build_alternation(["swap", "interest rate swap", "rate swap"])
    assert result.startswith("(?:interest rate swap|")


def test_build_alternation_auto_escape_and_compact() -> None:
    result = build_alternation(["10-K", "10-Q"], auto_escape=True, compact=True)
    assert result == r"(?:10\-[KQ])"


def test_add_restrictions() -> None:
    restricted = add_restrictions("item", lookbehinds="see", lookaheads="1")
    assert restricted == "(?<!see[- ])item(?![- ]1)"


def test_build_compound() -> None:
    compound = build_compound(prefix="form", core=["10-k", "10-q"], auto_escape=True)
    assert compound == r"form[- ](?:10\-k|10\-q)"


def test_build_regex() -> None:
    pattern = build_regex(["Form 10-K", "Form 10-Q"])
    assert pattern.search("Filed under Form 10-K for year end") is not None
    assert pattern.search("No match here") is None


def test_plural() -> None:
    assert plural("agreement?") == "agreement"
    assert plural("agreement") == "agreement"
