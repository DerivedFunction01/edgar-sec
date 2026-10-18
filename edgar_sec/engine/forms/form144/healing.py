"""Form 144 instruction sentence and phrase sequence healing."""

from __future__ import annotations

from collections.abc import Sequence
import re

from edgar_sec.domain.forms.families.form144.rules import FORM144_PHRASE_RULES
from edgar_sec.foundation.regex.builder import build_alternation
from edgar_sec.foundation.text.dates import heal_date_fragments
from edgar_sec.foundation.text.healing import heal_split_lines

_INSTRUCTION_PREFIX_WORDS = (
    "instructions",
    "instruction",
    "attention",
    "note",
    "notice",
)
_INSTRUCTION_PREFIX_ALT = build_alternation(_INSTRUCTION_PREFIX_WORDS)
_INSTRUCTION_START_PREFIXES = (
    rf"{_INSTRUCTION_PREFIX_ALT}\s*:",
    r"[123]\s*\.\s*\(",
    r"potential persons who are to respond",
)
_INSTRUCTION_START_ALT = build_alternation(_INSTRUCTION_START_PREFIXES)
_INSTRUCTION_START_RE = re.compile(rf"^\s*(?:{_INSTRUCTION_START_ALT})", re.IGNORECASE)
_DELIMITER_RE = re.compile(r"^[\s\-=_]{4,}$")
_SENTENCE_END_RE = re.compile(r"[\.\!\?]\s*$")
_BOX_START_RE = re.compile(r"^\s*[123]\s*\(")


def heal_instruction_sentences(lines: Sequence[str]) -> list[str]:
    """Merge wrapped multi-line instruction boilerplate into single sentence lines."""
    healed: list[str] = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        stripped = line.strip()
        if _INSTRUCTION_START_RE.match(stripped):
            sent_parts = [stripped]
            i += 1
            while i < n:
                next_l = lines[i].strip()
                if (
                    not next_l
                    or _DELIMITER_RE.match(next_l)
                    or _INSTRUCTION_START_RE.match(next_l)
                ):
                    break
                if _BOX_START_RE.match(next_l):
                    break
                if _SENTENCE_END_RE.search(sent_parts[-1]):
                    if not next_l.startswith(
                        ("(", "and ", "or ", "to ", "for ", "the ")
                    ):
                        break
                sent_parts.append(next_l)
                i += 1
            healed.append(" ".join(sent_parts))
        else:
            healed.append(line)
            i += 1
    return healed


def heal_form144_lines(lines: Sequence[str]) -> list[str]:
    """Heal Form 144 instruction sentences, phrase sequence rules, and dates."""
    instruction_healed = heal_instruction_sentences(lines)
    phrase_healed = heal_split_lines(instruction_healed, rules=FORM144_PHRASE_RULES)
    return heal_date_fragments(phrase_healed)


__all__ = ["heal_form144_lines", "heal_instruction_sentences"]
