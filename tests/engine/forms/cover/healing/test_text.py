"""Unit tests for edgar_sec.engine.forms.cover.healing.text."""

from __future__ import annotations

from edgar_sec.engine.forms.cover.healing.text import heal_cover_text
from edgar_sec.engine.forms.cover.models import BoundaryMethod, CoverBoundary
from edgar_sec.foundation.text.healing import PhraseSequenceRule


def test_heal_cover_text_none_boundary() -> None:
    boundary = CoverBoundary(
        end_line=None,
        end_offset=None,
        method=BoundaryMethod.UNKNOWN,
        confidence=0.0,
    )
    text = "Line 1\nLine 2"
    healed, changed = heal_cover_text(text, boundary, ())
    assert healed == text
    assert not changed


def test_heal_cover_text_preserves_tagged_tables() -> None:
    boundary = CoverBoundary(
        end_line=5,
        end_offset=None,
        method=BoundaryMethod.STRUCTURAL,
        confidence=0.9,
    )
    text = (
        "UNITED STATES\n"
        "<TABLE><TR><TD>Preserved Table</TD></TR></TABLE>\n"
        "SECURITIES AND EXCHANGE COMMISSION\n"
        "Accelerated filer [x]\n"
        "End of cover\n"
        "Body line 1\n"
        "Body line 2"
    )
    rules = [
        PhraseSequenceRule(
            name="sec_banner",
            tokens=["united", "states", "securities", "and", "exchange", "commission"],
            anchor=["securities"],
        )
    ]
    healed, changed = heal_cover_text(text, boundary, rules, reflow_prose=False)
    assert changed
    assert "<TABLE><TR><TD>Preserved Table</TD></TR></TABLE>" in healed
    assert "Accelerated filer [X]" in healed
    assert "Body line 1" in healed


def test_heal_cover_text_binary_blocks_html() -> None:
    boundary = CoverBoundary(
        end_line=5,
        end_offset=None,
        method=BoundaryMethod.STRUCTURAL,
        confidence=0.9,
    )
    text = "...Securities Act. Yes\n[ ]\nNo\nx\nEnd of cover\nBody line"
    healed, changed = heal_cover_text(
        text, boundary, (), merge_binary_blocks=True, reflow_prose=False
    )
    assert changed
    assert "...Securities Act. Yes [ ] No [X]" in healed
