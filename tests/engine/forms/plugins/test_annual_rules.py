"""Unit tests for edgar_sec.engine.forms.plugins.annual_rules."""

from __future__ import annotations

from edgar_sec.engine.forms.plugins.annual_rules import (
    ANNUAL_PHRASE_RULES,
    AUDITOR_RULES,
    DOCUMENTS_INCORPORATED_RULES,
    EXTENDED_TRANSITION_RULES,
    PUBLIC_FLOAT_RULES,
    SHARES_RULES,
)
from edgar_sec.foundation.text.healing import heal_split_lines


def test_annual_rules_composition() -> None:
    assert len(ANNUAL_PHRASE_RULES) > 0
    assert all(r in ANNUAL_PHRASE_RULES for r in SHARES_RULES)
    assert all(r in ANNUAL_PHRASE_RULES for r in PUBLIC_FLOAT_RULES)
    assert all(r in ANNUAL_PHRASE_RULES for r in DOCUMENTS_INCORPORATED_RULES)
    assert all(r in ANNUAL_PHRASE_RULES for r in AUDITOR_RULES)
    assert all(r in ANNUAL_PHRASE_RULES for r in EXTENDED_TRANSITION_RULES)


def test_documents_incorporated_healing() -> None:
    lines = [
        "DOCUMENTS",
        "INCORPORATED BY REFERENCE",
    ]
    healed = heal_split_lines(lines, DOCUMENTS_INCORPORATED_RULES)
    assert healed == ["DOCUMENTS INCORPORATED BY REFERENCE"]


def test_auditor_info_healing() -> None:
    lines = [
        "Auditor",
        "Firm ID: 1234",
    ]
    healed = heal_split_lines(lines, AUDITOR_RULES)
    assert healed == ["Auditor Firm ID: 1234"]
