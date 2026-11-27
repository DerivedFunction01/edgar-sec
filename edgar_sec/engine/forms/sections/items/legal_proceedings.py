"""Item 3 legal proceedings emission behind the section detector.

Consumes a detected section sequence and emits the Item 3 section's
span with its disposition: a negative-disclosure stub, an omission,
a cross-reference to disclosure elsewhere, or substantive prose.
"""

from __future__ import annotations

import re

from edgar_sec.engine.forms.sections.models import (
    LegalProceedingsDisposition,
    LegalProceedingsSection,
    ResolvedSection,
    SectionSequence,
)

_RE_SUBJECT = re.compile(r"legal\s+proceedings", re.IGNORECASE)
_RE_LEADING_PUNCT = re.compile(r"^[\s:.\-\u2013\u2014]+")
_RE_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_RE_REFERENCE = re.compile(
    r"incorporat|by reference|reference is made|\bsee\b|set forth in"
    r"|included in|described in|disclosed in",
    re.IGNORECASE,
)
_RE_STRONG_REFERENCE = re.compile(
    r"incorporat|by reference|reference is made", re.IGNORECASE
)

_NONE_MARKERS = frozenset({"none", "not applicable", "n/a"})
_OMITTED_MARKERS = frozenset(
    {"omitted", "[omitted]", "(omitted)", "reserved", "[reserved]"}
)


def _body_text(sequence: SectionSequence, text: str, section: ResolvedSection) -> str:
    """Section text past the heading: the heading line's tail plus the
    remaining lines, with a title carried on its own line removed.
    """
    raw = sequence.get_text(text, section.item_identifier)
    first, _, rest = raw.partition("\n")
    match = _RE_SUBJECT.search(first)
    if match:
        tail = _RE_LEADING_PUNCT.sub("", first[match.end() :]).strip()
        return "\n".join(part for part in (tail, rest) if part).strip()
    lines = rest.split("\n")
    if lines and " ".join(lines[0].lower().split()).rstrip(" .:") == (
        "legal proceedings"
    ):
        lines = lines[1:]
    return "\n".join(lines).strip()


def _is_cross_reference(body: str) -> bool:
    """Whether every sentence of the body only points at disclosure
    elsewhere, with at least one incorporation-grade reference.
    """
    sentences = [s for s in _RE_SENTENCE_SPLIT.split(body.strip()) if s.strip()]
    if not sentences or not _RE_STRONG_REFERENCE.search(body):
        return False
    return all(_RE_REFERENCE.search(sentence) for sentence in sentences)


def _classify(body: str) -> LegalProceedingsDisposition:
    """Disposition of one Item 3 section body, in priced-class order."""
    normalized = " ".join(body.lower().split()).rstrip(".")
    if normalized in _OMITTED_MARKERS:
        return LegalProceedingsDisposition.OMITTED
    if not normalized or normalized in _NONE_MARKERS:
        return LegalProceedingsDisposition.NONE
    if _is_cross_reference(body):
        return LegalProceedingsDisposition.CROSS_REFERENCE
    return LegalProceedingsDisposition.SUBSTANTIVE


def extract_legal_proceedings(
    sequence: SectionSequence, text: str
) -> LegalProceedingsSection | None:
    """Emit the Item 3 span and disposition from a detected sequence."""
    section = sequence.get("ITEM 3")
    if section is None:
        return None
    return LegalProceedingsSection(
        start_line=section.start_line,
        end_line=section.end_line,
        start_char=section.start_char,
        end_char=section.end_char,
        disposition=_classify(_body_text(sequence, text, section)),
    )
