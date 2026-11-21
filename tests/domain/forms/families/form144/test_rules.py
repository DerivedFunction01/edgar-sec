"""Tests for Form 144 phrase sequence rules."""

from __future__ import annotations

from edgar_sec.domain.forms.families.form144.rules import FORM144_PHRASE_RULES
from edgar_sec.foundation.text.healing import heal_split_lines


def test_form144_phrase_rules_join_split_labels() -> None:
    """Verify split Form 144 labels merge into intact lines."""
    lines = [
        "1(a)",
        "NAME OF ISSUER",
        "Pinnacle West",
        "2(a)",
        "NAME OF PERSON FOR WHOSE ACCOUNT",
        "THE SECURITIES ARE TO BE SOLD",
        "Pamela Grant",
        "3(a)",
        "Title of the Class of Securities To Be Sold",
        "Common Stock",
        "3(c)",
        "Number of Shares or Other Units To Be Sold",
        "5,574",
    ]
    healed = heal_split_lines(lines, FORM144_PHRASE_RULES)
    assert "1(a) NAME OF ISSUER" in healed
    assert (
        "2(a) NAME OF PERSON FOR WHOSE ACCOUNT THE SECURITIES ARE TO BE SOLD" in healed
    )
    assert "3(a) Title of the Class of Securities To Be Sold" in healed
    assert "3(c) Number of Shares or Other Units To Be Sold" in healed
    assert "Pinnacle West" in healed
    assert "Pamela Grant" in healed
    assert "Common Stock" in healed
    assert "5,574" in healed
