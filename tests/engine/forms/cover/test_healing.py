"""Unit tests for edgar_sec.engine.forms.cover.healing."""

from __future__ import annotations

from edgar_sec.domain.forms.checkmarks import CANONICAL_CHECKED, CANONICAL_UNCHECKED
from edgar_sec.engine.forms.cover.healing import (
    heal_cover_text,
    normalize_checkbox_tokens,
)
from edgar_sec.engine.forms.cover.models import BoundaryMethod, CoverBoundary
from edgar_sec.foundation.text.healing import PhraseSequenceRule


def test_normalize_checkbox_tokens() -> None:
    text = "Large accelerated filer [x] Non-accelerated filer [ ] (X)"
    normalized = normalize_checkbox_tokens(text)
    assert CANONICAL_CHECKED in normalized
    assert CANONICAL_UNCHECKED in normalized


def test_heal_cover_text_end_line_none() -> None:
    boundary = CoverBoundary(
        end_line=None,
        end_offset=None,
        method=BoundaryMethod.UNKNOWN,
        confidence=0.0,
    )
    text = "Some unhealed cover text"
    healed, changed = heal_cover_text(text, boundary)
    assert healed == text
    assert not changed


def test_heal_cover_text_healing_rules_and_dates() -> None:
    boundary = CoverBoundary(
        end_line=5,
        end_offset=100,
        method=BoundaryMethod.STRUCTURAL,
        confidence=1.0,
    )
    rules = [
        PhraseSequenceRule(
            name="sec_header",
            tokens=["united", "states", "securities", "and", "exchange", "commission"],
            anchor=["securities"],
        )
    ]
    text = (
        "UNITED STATES\n"
        "SECURITIES AND EXCHANGE COMMISSION\n"
        "December\n"
        "31,\n"
        "2024\n"
        "ITEM 1. BUSINESS\n"
        "This is the body."
    )
    healed, changed = heal_cover_text(text, boundary, rules)
    assert changed
    lines = healed.splitlines()
    assert lines[0] == "UNITED STATES SECURITIES AND EXCHANGE COMMISSION"
    assert lines[1] == "December 31, 2024"
    assert lines[2] == "ITEM 1. BUSINESS"
    assert lines[3] == "This is the body."
