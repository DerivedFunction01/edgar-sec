"""Signature-region location, masking, and letter-spaced name healing.

A signature block is a layout, not a token: a conformed ``/s/`` line, a name
line, a title line, a date, and an underline, often in two columns. A reflow
that rewrites one of those lines into a different column corrupts the block, so
the whole region is masked before any line-level rewrite and restored after.

The mask preserves the line count and the exact source bytes, which is the
contract that makes it safe: a caller may rewrite anything between the two calls
and still get the original signature block back, character for character.

Mangled names are a known SEC artifact of condensed fonts. Glyph-width
rendering inserts a space after an isolated uppercase letter, producing
``/s/ S ATYA N ADELLA`` or ``M ICROSOFT C ORPORATION``. Healing removes the
whitespace only after isolated single-letter uppercase tokens, and only once
the signature-marker context confirms the mangled shape, so an ordinary
capitalized name with real initials keeps its spacing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from edgar_sec.foundation.regex.builder import build_alternation
from edgar_sec.foundation.text.dates import (
    NUMERIC_DATE_RE,
    contains_date,
)

# Conformed signature line: an optional ``*`` or ``By:`` label followed by ``/s/``.
RE_CONFORMED_SIGNATURE = re.compile(r"^\s*(?:\*\s*)?(?:By\s*:\s*|By\s+)?/\s*s\s*/\s*")

# Power of attorney signer: ``*By: [Name]`` or ``*By: [Name], Attorney-in-Fact``
RE_POA_SIGNER = re.compile(r"^\s*\*\s*(?:By\s*:\s*|By\s+)", re.IGNORECASE)
_SIGNATURE_ASTERISK_RE = re.compile(r"^\s*[*]+\s*$")

# A signature marker followed by a letter-spaced name: ``/s/ A LICE L. J OLLA``
# or ``/ S / S ATYA N ADELLA``. Requires at least one isolated single-letter
# uppercase token pair after the marker so ordinary ``/s/ Alex Smith`` never
# triggers healing.
_MANGLED_SIGNATURE_RE = re.compile(r"/\s*[sS]\s*/\s+[A-Z]\s+[A-Z]")

# Isolated single uppercase letter followed by whitespace and another
# uppercase letter. Only applied when the mangled-signature context is
# confirmed; never applied to arbitrary text.
_ISOLATED_CAPITAL_GAP_RE = re.compile(r"\b([A-Z])\s+(?=[A-Z])")

# Canonical marker with optional leading ``By:`` label.
_MARKER_RE = re.compile(r"^(/\s*S\s*/|/s/)\s*", re.IGNORECASE)
_SIGNATURE_HEADER_RE = re.compile(
    rf"^\s*(?:{build_alternation(('signature', 'name'), auto_escape=True)})\b.*\b"
    rf"(?:{build_alternation(('title', 'position', 'date'), auto_escape=True)})\b",
    re.IGNORECASE,
)
_SIGNATURE_UNDERLINE_RE = re.compile(r"^\s*[_=-]{3,}\s*$")

_SIGNATURE_TITLE_RE = re.compile(
    rf"\b(?:{build_alternation(('director', 'officer', 'president', 'treasurer', 'secretary', 'chief', 'vice', 'principal', 'accounting', 'financial', 'executive', 'attorney'), auto_escape=True)})\b",
    re.IGNORECASE,
)
_SIGNATURE_LAYOUT_GAP_RE = re.compile(r"\s{2,}|\t")


SIGNATURE_LABEL_PREFIXES: tuple[str, ...] = (
    "/s/ ",
    "By:",
    "Name:",
    "Title:",
    "Date:",
    "Signature:",
)
RE_SIGNATURE_LABEL_LINE = re.compile(
    rf"^\s*(?:\*\s*)?(?:{build_alternation(SIGNATURE_LABEL_PREFIXES, auto_escape=True)})\s*",
    re.IGNORECASE,
)


def is_signature_label_line(line: str) -> bool:
    """Return whether a line opens a shared signature-block label.

    A line starting with one of these is layout rather than prose, so a reflow
    must leave the block containing it alone. It lives here rather than with the
    reflow feature that reads it, because the label vocabulary is a property of
    signatures and this is the module that owns them.
    """
    return bool(RE_SIGNATURE_LABEL_LINE.match(line))


@dataclass(frozen=True, slots=True)
class SignatureRegion:
    """One complete, line-preserving signature layout region."""

    start_line: int
    end_line: int
    aligned: bool
    confidence: float
    signer_count: int
    lines: tuple[str, ...] = ()


def is_conformed_signature_line(line: str) -> bool:
    """Return whether a raw line starts with a conformed marker or POA signature."""
    if "/" in line:
        return bool(RE_CONFORMED_SIGNATURE.match(line))
    return bool("*" in line and RE_POA_SIGNER.match(line))


def _signature_row(line: str, previous: str = "") -> bool:
    """Return whether a line continues a signature layout.

    Three independent signals, any one of which is enough: a conformed marker
    or an underline, a date, or an indented alphabetic line following another
    signature row. The last requires a multi-space or tab gap, because an
    indented continuation is a layout fact and an indented heading is not.
    """
    stripped = line.strip()
    if not stripped:
        return False
    if is_conformed_signature_line(line):
        return True
    if _SIGNATURE_ASTERISK_RE.fullmatch(line):
        return True
    first_char = stripped[0]
    if (
        first_char in "_=-"
        and len(stripped) >= 3
        and _SIGNATURE_UNDERLINE_RE.fullmatch(line)
    ):
        return True
    if "  " not in line and "\t" not in line:
        return False
    has_date = bool(contains_date(line) or NUMERIC_DATE_RE.search(line))
    if has_date or _SIGNATURE_TITLE_RE.search(line):
        return bool(_SIGNATURE_LAYOUT_GAP_RE.search(line))
    if previous and line[:1].isspace() and any(char.isalpha() for char in stripped):
        return bool(_SIGNATURE_LAYOUT_GAP_RE.search(line))
    return False


def find_signature_regions(
    lines: tuple[str, ...] | list[str],
) -> tuple[SignatureRegion, ...]:
    """Find complete signature layouts, allowing blank lines between signers.

    A region must contain more than its opening line, and must have been opened
    by either a title-bearing header or at least one conformed marker. A lone
    conformed line, or a run of indented text with no marker and no header, is
    not a signature block and is left to the ordinary text stages.
    """
    source = tuple(lines)
    regions: list[SignatureRegion] = []
    index = 0
    n = len(source)
    while index < n:
        line = source[index]
        s_line = line.lstrip()
        is_header = bool(
            s_line and s_line[0] in "sSnN" and _SIGNATURE_HEADER_RE.match(line)
        )
        if not (is_header or _signature_row(line)):
            index += 1
            continue
        start = index
        last_signal = index
        signer_count = 0
        saw_header = is_header
        previous = ""
        index += 1
        while index < n:
            curr_line = source[index]
            if not curr_line.strip():
                index += 1
                continue
            if _signature_row(curr_line, previous):
                last_signal = index
                signer_count += int(is_conformed_signature_line(curr_line))
                previous = curr_line
                index += 1
                continue
            break
        if last_signal > start and (saw_header or signer_count):
            end = last_signal + 1
            region_lines = source[start:end]
            aligned = (
                sum(
                    bool(_SIGNATURE_LAYOUT_GAP_RE.search(line)) for line in region_lines
                )
                >= 2
            )
            regions.append(
                SignatureRegion(
                    start,
                    end,
                    aligned,
                    0.95 if saw_header and signer_count else 0.8,
                    signer_count,
                    region_lines,
                )
            )
        index = max(index, last_signal + 1)
    return tuple(regions)


def mask_signature_regions(
    text: str,
) -> tuple[str, tuple[SignatureRegion, ...]]:
    """Mask signature lines while preserving line count and exact source text.

    One token per line, named by region index and line offset within the
    region, so a later restore is unambiguous even when two regions in the same
    document have the same shape. The trailing newline of each masked line is
    preserved, which is what keeps every downstream line index valid.
    """
    if "/" not in text and "*" not in text:
        lower = text.lower()
        if "signature" not in lower and "name" not in lower:
            return text, ()
    lines = text.splitlines(keepends=True)
    regions = find_signature_regions(tuple(line.rstrip("\r\n") for line in lines))
    if not regions:
        return text, ()
    masked = list(lines)
    for region_index, region in enumerate(regions):
        for line_index in range(region.start_line, region.end_line):
            ending = "\n" if masked[line_index].endswith("\n") else ""
            masked[line_index] = (
                f"__SEC_SIG_{region_index}_{line_index - region.start_line}__{ending}"
            )
    return "".join(masked), regions


def restore_signature_regions(text: str, regions: tuple[SignatureRegion, ...]) -> str:
    """Restore masked signature lines exactly once.

    The token is a whole-token replacement, so a caller that has rewritten a
    masked line gets the original back; that is the intended behaviour and the
    reason the mask is a token and not a character-count pad.
    """
    if not regions:
        return text
    restored = text
    for region_index, region in enumerate(regions):
        for line_index, line in enumerate(region.lines):
            token = f"__SEC_SIG_{region_index}_{line_index}__"
            restored = restored.replace(token, line)
    return restored


def normalize_signature_marker(text: str) -> str:
    """Return ``text`` with its leading signature marker canonicalized.

    ``/S/``, ``/ S /``, ``/ s /`` and ``/s/`` all become ``/s/``. Any other
    text is returned unchanged.
    """
    match = _MARKER_RE.match(text)
    if not match:
        return text
    return (
        f"/s/ {text[match.end() :].strip()}" if text[match.end() :].strip() else "/s/"
    )


def signature_block_has_mangled_text(cells: tuple[str, ...] | list[str]) -> bool:
    """Return whether any cell carries the mangled marker-plus-name shape."""
    return any(_MANGLED_SIGNATURE_RE.search(cell) for cell in cells)


def heal_mangled_signature_text(text: str) -> str:
    """Heal letter-spaced signature text inside a confirmed mangled block.

    Collapses whitespace after isolated single-letter uppercase tokens and
    canonicalizes the marker. Ordinary capitalized names with real initials
    (``A. Smith``) keep their spacing because the initial keeps its period.
    """
    healed = _ISOLATED_CAPITAL_GAP_RE.sub(r"\1", text)
    return normalize_signature_marker(healed)


__all__ = [
    "RE_CONFORMED_SIGNATURE",
    "RE_POA_SIGNER",
    "SignatureRegion",
    "find_signature_regions",
    "heal_mangled_signature_text",
    "is_conformed_signature_line",
    "mask_signature_regions",
    "normalize_signature_marker",
    "restore_signature_regions",
    "signature_block_has_mangled_text",
]
