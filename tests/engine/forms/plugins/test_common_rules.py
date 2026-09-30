"""Unit tests for edgar_sec.engine.forms.plugins.common_rules."""

from __future__ import annotations

from edgar_sec.engine.forms.plugins.common_rules import (
    BANNER_RULES,
    COMMON_PHRASE_RULES,
    CONTACT_CAPTION_RULES,
    FORM_TITLE_RULES,
    PERIOD_FILE_REGISTRANT_RULES,
    REGISTRATION_RULES,
)
from edgar_sec.foundation.text.healing import heal_split_lines


def test_common_phrase_rules_composition() -> None:
    assert len(COMMON_PHRASE_RULES) > 0
    assert all(r in COMMON_PHRASE_RULES for r in BANNER_RULES)
    assert all(r in COMMON_PHRASE_RULES for r in FORM_TITLE_RULES)
    assert all(r in COMMON_PHRASE_RULES for r in PERIOD_FILE_REGISTRANT_RULES)
    assert all(r in COMMON_PHRASE_RULES for r in CONTACT_CAPTION_RULES)
    assert all(r in COMMON_PHRASE_RULES for r in REGISTRATION_RULES)


def test_sec_banner_healing() -> None:
    lines = [
        "UNITED STATES",
        "SECURITIES AND EXCHANGE COMMISSION",
    ]
    healed = heal_split_lines(lines, COMMON_PHRASE_RULES)
    assert healed == ["UNITED STATES SECURITIES AND EXCHANGE COMMISSION"]


def test_report_pursuant_act_healing() -> None:
    lines = [
        "[X] ANNUAL REPORT PURSUANT TO SECTION 13 OR 15(d) OF THE SECURITIES EXCHANGE ACT",
        "OF 1934",
    ]
    healed = heal_split_lines(lines, COMMON_PHRASE_RULES)
    assert healed == [
        "[X] ANNUAL REPORT PURSUANT TO SECTION 13 OR 15(d) OF THE SECURITIES EXCHANGE ACT OF 1934"
    ]
