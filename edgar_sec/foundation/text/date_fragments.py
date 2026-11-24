"""Healing for SEC dates split across adjacent text lines."""

from __future__ import annotations

from collections.abc import Sequence
import re

from edgar_sec.foundation.text.date_patterns import (
    MONTH_PATTERN,
    MONTH_RE,
    YEAR_IN_TEXT_RE,
)
from edgar_sec.foundation.text.dates import parse_date


_RE_SLASH_SEP = re.compile(r"\s*/\s*")


_RE_DASH_SEP = re.compile(r"\s*-\s*")


_RE_DATE_FRAGMENT = re.compile(
    r"(?:\d{1,4}(?:st|nd|rd|th)?|[,./-])(?:\s*[,./-]?\s*)?",
    re.IGNORECASE,
)


def heal_date_fragments(
    lines: Sequence[str],
    *,
    max_window: int = 4,
) -> list[str]:
    """Join split date fragments across adjacent lines."""
    result = list(lines)
    i = 0
    while i < len(result):
        if i >= len(result):
            break
        candidate, end_idx = _scan_date_window(result, i, max_window=max_window)
        if candidate is not None:
            parsed = parse_date(candidate)
            if parsed is not None:
                result[i : end_idx + 1] = [parsed.display]
                continue
        i += 1
    return result


def _scan_date_window(
    lines: list[str],
    start: int,
    *,
    max_window: int,
) -> tuple[str | None, int]:
    parts: list[str] = []
    end = start
    best: tuple[str, int] | None = None
    for offset in range(max_window):
        idx = start + offset
        if idx >= len(lines):
            break
        text = lines[idx].strip()
        if not text:
            break
        # Date healing is intentionally limited to date-only fragments. A
        # permissive date parser can find an embedded date in arbitrary prose
        # and replacing the whole window would silently discard that prose.
        if not _is_date_fragment(text):
            break
        parts.append(text)
        end = idx
        if offset > 0:
            candidate = _normalize_separators(" ".join(parts))
            if parse_date(candidate) is not None:
                best = (candidate, end)
    if best is not None:
        return best
    if len(parts) > 1 and _looks_like_date_fragment(parts):
        return _normalize_separators(" ".join(parts)), end
    return None, start


_RE_MONTH_DAY_FRAGMENT = re.compile(rf"(?i)^(?:{MONTH_PATTERN})\s+\d{{1,2}},?$")


_RE_DAY_YEAR_FRAGMENT = re.compile(r"^\d{1,2},?\s+\d{2,4}$")


def _is_date_fragment(text: str) -> bool:
    """Return whether a line contains only one fragment of a date."""
    normalized = text.strip()
    if not normalized:
        return False
    if MONTH_RE.fullmatch(normalized.rstrip(".")):
        return True
    if _RE_DATE_FRAGMENT.fullmatch(normalized):
        return True
    if _RE_MONTH_DAY_FRAGMENT.match(normalized):
        return True
    return bool(_RE_DAY_YEAR_FRAGMENT.match(normalized))


def _normalize_separators(text: str) -> str:
    """Collapse spaces around slash and dash date separators."""
    return _RE_SLASH_SEP.sub("/", _RE_DASH_SEP.sub("-", text))


def _looks_like_date_fragment(parts: list[str]) -> bool:
    combined = " ".join(parts)
    if MONTH_RE.search(combined):
        return True
    return bool(
        YEAR_IN_TEXT_RE.search(combined) and ("/" in combined or "-" in combined)
    )


__all__ = [
    "heal_date_fragments",
]
