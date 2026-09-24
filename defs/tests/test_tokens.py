"""Unit and contract tests for defs.text.tokens."""

from __future__ import annotations

import re

import pytest

from defs.text.tokens import (
    ROMAN_NUMERAL_PATTERN,
    is_bullet_line,
    is_list_or_bullet_marker,
    is_ordered_marker_prefix,
    is_wrapped_marker_prefix,
    roman_to_int,
)


def test_roman_numeral_pattern() -> None:
    pat = re.compile(rf"^{ROMAN_NUMERAL_PATTERN}$", re.IGNORECASE)
    assert pat.fullmatch("i")
    assert pat.fullmatch("iv")
    assert pat.fullmatch("VIII")
    assert pat.fullmatch("xvi")
    assert pat.fullmatch("cxxiii")
    assert pat.fullmatch("mmmcmxcix") is None  # length > 8
    assert pat.fullmatch("abc") is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("i", 1),
        ("ii", 2),
        ("iii", 3),
        ("iv", 4),
        ("v", 5),
        ("vi", 6),
        ("ix", 9),
        ("x", 10),
        ("xiv", 14),
        ("xxiv", 24),
        ("xl", 40),
        ("l", 50),
        ("xc", 90),
        ("c", 100),
        ("cd", 400),
        ("d", 500),
        ("cm", 900),
        ("m", 1000),
        ("mcmxl", 1940),
        ("mmm", 3000),
        ("IV", 4),
        ("XIX", 19),
        ("XX", 20),
    ],
)
def test_roman_to_int_valid(text: str, expected: int) -> None:
    assert roman_to_int(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "",
        "0",
        "123",
        "iiii",
        "iiiv",
        "vx",
        "ic",
        "xd",
        "mmmm",  # > 3000
        "abc",
        "ivx",
    ],
)
def test_roman_to_int_invalid(text: str) -> None:
    assert roman_to_int(text) is None


def test_bullet_and_list_helpers() -> None:
    assert is_bullet_line("• Item 1")
    assert is_bullet_line("- Item 2")
    assert not is_bullet_line("Regular prose sentence.")

    assert is_list_or_bullet_marker("•")
    assert is_list_or_bullet_marker("-")
    assert not is_list_or_bullet_marker("word")

    assert is_ordered_marker_prefix("1. Introduction")
    assert is_ordered_marker_prefix("iv. Analysis")
    assert is_ordered_marker_prefix("A. Appendix")
    assert not is_ordered_marker_prefix("Introduction")

    assert is_wrapped_marker_prefix("(1) Note")
    assert is_wrapped_marker_prefix("(iv) Subclause")
    assert is_wrapped_marker_prefix("(a) Section")
    assert not is_wrapped_marker_prefix("Note")
