"""Text-level signature primitives: marker normalization and name healing."""

from __future__ import annotations

import re
from dataclasses import dataclass

from edgar_sec.foundation.regex.builder import build_alternation
from edgar_sec.foundation.text.dates import contains_date

RE_CONFORMED_SIGNATURE = re.compile(r"^\s*(?:By\s*:\s*)?/s/\s*")

SIGNATURE_LABEL_PREFIXES: tuple[str, ...] = (
    "/s/ ",
    "By:",
    "Name:",
    "Title:",
    "Date:",
    "Signature:",
)
RE_SIGNATURE_LABEL_LINE = re.compile(
    rf"^\s*(?:{build_alternation(SIGNATURE_LABEL_PREFIXES, auto_escape=True)})\s*",
    re.IGNORECASE,
)

_MANGLED_MARKER_RE = re.compile(r"/\s+S\s+/|/\s+s\s+/")
_MANGLED_SIGNATURE_RE = re.compile(r"/\s*[sS]\s*/\s+[A-Z]\s+[A-Z]")
_ISOLATED_CAPITAL_GAP_RE = re.compile(r"\b([A-Z])\s+(?=[A-Z])")
_MARKER_RE = re.compile(r"^(/\s*S\s*/|/s/)\s*", re.IGNORECASE)

_SIGNATURE_HEADER_RE = re.compile(
    rf"^\s*(?:{build_alternation(('signature', 'name'), auto_escape=True)})\b.*\b"
    rf"(?:{build_alternation(('title', 'position', 'date'), auto_escape=True)})\b",
    re.IGNORECASE,
)
_SIGNATURE_UNDERLINE_RE = re.compile(r"^\s*[_=-]{3,}\s*$")
_SIGNATURE_TITLE_RE = re.compile(
    rf"\b(?:{build_alternation(('director', 'officer', 'president', 'treasurer', 'secretary', 'chief', 'vice', 'principal', 'accounting', 'financial', 'executive'), auto_escape=True)})\b",
    re.IGNORECASE,
)
_SIGNATURE_LAYOUT_GAP_RE = re.compile(r"\s{2,}|\t")


@dataclass(frozen=True, slots=True)
class SignatureRegion:
    """One complete, line-preserving signature layout region."""

    start_line: int
    end_line: int
    aligned: bool
    confidence: float
    signer_count: int
    lines: tuple[str, ...] = ()


def _signature_row(line: str, previous: str = "") -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if is_conformed_signature_line(line) or _SIGNATURE_UNDERLINE_RE.fullmatch(line):
        return True
    has_date = contains_date(line, include_partial=True)
    if has_date or _SIGNATURE_TITLE_RE.search(line):
        return bool(_SIGNATURE_LAYOUT_GAP_RE.search(line))
    if previous and line[:1].isspace() and any(char.isalpha() for char in stripped):
        return bool(_SIGNATURE_LAYOUT_GAP_RE.search(line))
    return False


def find_signature_regions(
    lines: tuple[str, ...] | list[str],
) -> tuple[SignatureRegion, ...]:
    """Find complete signature layouts, allowing blank lines between signers."""
    source = tuple(lines)
    regions: list[SignatureRegion] = []
    index = 0
    while index < len(source):
        if not (
            _SIGNATURE_HEADER_RE.match(source[index]) or _signature_row(source[index])
        ):
            index += 1
            continue
        start = index
        last_signal = index
        signer_count = 0
        saw_header = bool(_SIGNATURE_HEADER_RE.match(source[index]))
        previous = ""
        index += 1
        while index < len(source):
            line = source[index]
            if not line.strip():
                index += 1
                continue
            if _signature_row(line, previous):
                last_signal = index
                signer_count += int(is_conformed_signature_line(line))
                previous = line
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
    """Mask signature lines while preserving line count and exact source text."""
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
    """Restore masked signature lines exactly once."""
    if not regions:
        return text
    restored = text
    for region_index, region in enumerate(regions):
        for line_index, line in enumerate(region.lines):
            token = f"__SEC_SIG_{region_index}_{line_index}__"
            restored = restored.replace(token, line)
    return restored


def normalize_signature_marker(text: str) -> str:
    """Return text with its leading signature marker canonicalized."""
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
    """Heal letter-spaced signature text inside a confirmed mangled block."""
    healed = _ISOLATED_CAPITAL_GAP_RE.sub(r"\1", text)
    return normalize_signature_marker(healed)


def is_conformed_signature_line(line: str) -> bool:
    """Return whether a raw line starts with a conformed ``/s/`` marker."""
    return bool(RE_CONFORMED_SIGNATURE.match(line))


def is_signature_label_line(line: str) -> bool:
    """Return whether a line starts with a shared signature-block label."""
    return bool(RE_SIGNATURE_LABEL_LINE.match(line))


__all__ = [
    "RE_CONFORMED_SIGNATURE",
    "RE_SIGNATURE_LABEL_LINE",
    "SIGNATURE_LABEL_PREFIXES",
    "SignatureRegion",
    "find_signature_regions",
    "heal_mangled_signature_text",
    "is_conformed_signature_line",
    "is_signature_label_line",
    "mask_signature_regions",
    "normalize_signature_marker",
    "restore_signature_regions",
    "signature_block_has_mangled_text",
]
