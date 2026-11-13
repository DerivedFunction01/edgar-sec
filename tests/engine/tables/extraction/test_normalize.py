"""Pins for the extraction package's shared text normaliser."""

from __future__ import annotations

import pytest

from edgar_sec.engine.tables.extraction.normalize import (
    collapse_text,
    normalize_label,
    normalize_text,
)


def _former_canonical(text: str) -> str:
    return " ".join(text.lower().replace("’", "'").split()).strip(" :.")


def _former_label(text: str) -> str:
    return " ".join(text.lower().split()).strip(" :.")


def _former_collapse(text: str) -> str:
    return " ".join(text.split())


_BATTERY = (
    "",
    "  Total   Stockholders’ Equity:  ",
    "CONSOLIDATED\nBALANCE\tSHEETS.",
    " . : net  income : . ",
    "Stockholders’ equity",
    "no-change",
    "trailing...:::   ",
    "a b",
)


@pytest.mark.parametrize("text", _BATTERY)
def test_normalize_text_matches_former_copies(text: str) -> None:
    assert normalize_text(text) == _former_canonical(text)


@pytest.mark.parametrize("text", _BATTERY)
def test_normalize_label_matches_former_validation_copy(text: str) -> None:
    assert normalize_label(text) == _former_label(text)


@pytest.mark.parametrize("text", _BATTERY)
def test_collapse_text_matches_former_typed_rows_copy(text: str) -> None:
    assert collapse_text(text) == _former_collapse(text)


def test_normalize_text_folds_remaining_smart_quotes() -> None:
    # Named delta vs the former copies: the foundation fold also maps
    # U+2018, U+201C, and U+201D, which the copies left untouched.
    assert normalize_text("‘Total’ “Assets”") == "'total' \"assets\""
    assert _former_canonical("‘Total’ “Assets”") == "‘total' “assets”"


def test_variant_differences_are_pinned() -> None:
    # normalize_label never folds the right single quote; normalize_text does.
    assert normalize_label("Stockholders’ Equity") == "stockholders’ equity"
    assert normalize_text("Stockholders’ Equity") == "stockholders' equity"
    # collapse_text preserves case and edge punctuation; the others do not.
    assert collapse_text("  Total : Assets. ") == "Total : Assets."
    assert normalize_label("  Total : Assets. ") == "total : assets"
