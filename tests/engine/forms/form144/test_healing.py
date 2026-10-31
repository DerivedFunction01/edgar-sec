"""Tests for Form 144 instruction and sequence healing."""

from __future__ import annotations

from edgar_sec.engine.forms.form144.healing import (
    heal_form144_lines,
    heal_instruction_sentences,
)


def test_heal_instruction_sentences() -> None:
    """Verify multi-line instruction boilerplate is collapsed into one sentence."""
    lines = [
        "INSTRUCTION: The person filing this notice should contact the issuer to obtain",
        "             the I.R.S. Identification Number and the S.E.C. File Number.",
        "1(a) NAME OF ISSUER",
        "ATTENTION: Intentional misstatements or omission of facts constitute Federal",
        "Criminal Violations. (See 18 U.S.C. 1001.)",
    ]
    healed = heal_instruction_sentences(lines)
    assert len(healed) == 3
    assert "S.E.C. File Number." in healed[0]
    assert healed[1] == "1(a) NAME OF ISSUER"
    assert "Criminal Violations." in healed[2]


def test_heal_form144_lines_end_to_end() -> None:
    """Verify full Form 144 healing handles instructions and labels."""
    lines = [
        "INSTRUCTION: Contact the issuer to obtain",
        "the S.E.C. File Number.",
        "1(a)",
        "NAME OF ISSUER",
        "Acme Corp",
        "May 29,",
        "2001",
    ]
    healed = heal_form144_lines(lines)
    assert any(
        "Contact the issuer to obtain the S.E.C. File Number." in l for l in healed
    )
    assert any("1(a) NAME OF ISSUER" in l for l in healed)
    assert any("Acme Corp" in l for l in healed)
    assert any("May 29, 2001" in l for l in healed)
