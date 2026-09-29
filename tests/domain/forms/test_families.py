"""Tests for the canonical form-family alias registry."""

from __future__ import annotations

import pytest

from edgar_sec.domain.forms.families import (
    FORM_FAMILY_ALIASES,
    aliases_for_family,
    form_family,
    normalize_form,
    resolve_alias,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("10-K", "10-K"),
        ("10-K/A", "10-K"),
        ("10-K405", "10-K"),
        ("10-KSB", "10-K"),
        ("10KSB", "10-K"),
        ("10-KT", "10-K"),
        ("10-K/A-POS", "10-K"),
        ("10-Q", "10-Q"),
        ("10-QSB", "10-Q"),
        ("10-QT", "10-Q"),
        ("8-K", "8-K"),
        ("8-K12B", "8-K"),
        ("8-K12G3", "8-K"),
        ("8-K15D5", "8-K"),
        ("20-F", "20-F"),
        ("20FR12B", "20-F"),
        ("6-K", "6-K"),
    ],
)
def test_resolve_alias(raw: str, expected: str) -> None:
    assert resolve_alias(raw) == expected


def test_suffix_stripping_prefers_pos_before_amendment() -> None:
    assert form_family("10-K/A-POS") == "10-K"
    assert form_family("10-K/A_W") == "10-K"
    assert form_family("10-KMEF") == "10-K"


def test_all_suffixes_collapse_to_original() -> None:
    assert form_family("/A") == "/A"


def test_unknown_form_returns_none() -> None:
    assert resolve_alias("S-1") is None
    assert normalize_form("S-1") is None
    assert resolve_alias(None) is None
    assert resolve_alias("") is None


def test_aliases_for_family() -> None:
    assert "10-K405" in aliases_for_family("10-K")
    assert aliases_for_family("nope") == ()


def test_every_alias_resolves_to_its_own_family() -> None:
    for family, aliases in FORM_FAMILY_ALIASES.items():
        for alias in aliases:
            assert resolve_alias(alias) == family
