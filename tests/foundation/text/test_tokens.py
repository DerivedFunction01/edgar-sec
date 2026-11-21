"""Unit and contract tests for edgar_sec.foundation.text.tokens."""

from __future__ import annotations

import re

import pytest

from edgar_sec.foundation.text.tokens import (
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
        "abc",
    ],
)
def test_roman_to_int_invalid(text: str) -> None:
    assert roman_to_int(text) is None


def test_is_bullet_line() -> None:
    assert is_bullet_line("• Item one")
    assert is_bullet_line("- Another item")
    assert is_bullet_line("* Third item")
    assert is_bullet_line("1. Numbered item")
    assert is_bullet_line("(a) Letter item")
    assert is_bullet_line("(i) Roman item")
    assert not is_bullet_line("Just ordinary text")
    assert not is_bullet_line("")


def test_is_list_or_bullet_marker() -> None:
    assert is_list_or_bullet_marker("•")
    assert is_list_or_bullet_marker("-")
    assert is_list_or_bullet_marker("1.")
    assert is_list_or_bullet_marker("(a)")
    assert is_list_or_bullet_marker("(iv)")
    assert not is_list_or_bullet_marker("apple")
    assert not is_list_or_bullet_marker("")


def test_ordered_marker_prefixes() -> None:
    assert is_ordered_marker_prefix("1. ")
    assert is_ordered_marker_prefix("A. ")
    assert is_ordered_marker_prefix("iv. ")
    assert not is_ordered_marker_prefix("Company. ")

    assert is_wrapped_marker_prefix("(1) ")
    assert is_wrapped_marker_prefix("(a) ")
    assert is_wrapped_marker_prefix("(iv) ")
    assert not is_wrapped_marker_prefix("(Note) ")
