"""Modular date parsing and healing for SEC filings."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from defs.regex import build_alternation, compact_alternation

MONTH_NAMES = (
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
)

MONTH_ALIASES: tuple[tuple[str, ...], ...] = (
    ("january", "jan", "jan."),
    ("february", "feb", "feb."),
    ("march", "mar", "mar."),
    ("april", "apr", "apr."),
    ("may",),
    ("june", "jun", "jun."),
    ("july", "jul", "jul."),
    ("august", "aug", "aug."),
    ("september", "sep", "sept", "sep.", "sept."),
    ("october", "oct", "oct."),
    ("november", "nov", "nov."),
    ("december", "dec", "dec."),
)

_MONTH_NAME_TO_INDEX: dict[str, int] = {}
_MONTH_PATTERN_PARTS: list[str] = []
for index, aliases in enumerate(MONTH_ALIASES, start=1):
    _MONTH_NAME_TO_INDEX.update({alias: index for alias in aliases})
    for alias in aliases:
        _MONTH_PATTERN_PARTS.append(re.escape(alias))

MONTH_PATTERN = compact_alternation(_MONTH_PATTERN_PARTS)
MONTH_RE = re.compile(rf"(?i){MONTH_PATTERN}")
MONTH_NAME_RE = re.compile(rf"(?i)^(?:{MONTH_PATTERN})$")
ORDINAL_SUFFIX_PATTERN = build_alternation(
    [r"st", r"nd", r"rd", r"th"], auto_escape=True
)
MONTH_SUFFIX_RE = re.compile(rf"(?i)(?:{MONTH_PATTERN})\s*$")
ORDINAL_SUFFIX_RE = re.compile(rf"(?i)(\d+)(?:{ORDINAL_SUFFIX_PATTERN})\b")

YEAR_RANGE = (1900, 2100)
CENTURY_PIVOT = 50

YEAR_TOKEN_RE = re.compile(
    rf"^\b({build_alternation([r'19[0-9]{2}', r'20[0-9]{2}', r'2100'], auto_escape=False)})\b$"
)
YEAR_IN_TEXT_RE = re.compile(r"\b(\d{4})\b")
NUMERIC_YEAR_RE = re.compile(r"\b(\d{2,4})\b")
TABLE_YEAR_RE = re.compile(
    build_alternation([r"(?:\d{1,2}/)+(\d{2,4})", r"\b(\d{4})\b"], auto_escape=False)
)


@dataclass(frozen=True, slots=True)
class DateComponents:
    year: int
    month: int
    day: int

    def to_iso(self) -> str:
        return f"{self.year:04d}-{self.month:02d}-{self.day:02d}"

    def valid(self) -> bool:
        try:
            date(self.year, self.month, self.day)
            return True
        except ValueError:
            return False


@dataclass(frozen=True, slots=True)
class DateFormat:
    id: str
    pattern: str
    priority: int = 0


@dataclass(frozen=True, slots=True)
class ParsedDate:
    format_id: str
    source: str
    components: DateComponents
    ambiguous: bool = False

    @property
    def iso(self) -> str:
        return self.components.to_iso()

    @property
    def display(self) -> str:
        return self.source


def parse_year_token(
    value: str,
    *,
    valid_range: tuple[int, int] = YEAR_RANGE,
) -> int | None:
    """Parse a standalone numeric year token within the valid range."""
    match = YEAR_TOKEN_RE.match(value.strip())
    if not match:
        return None
    year = int(match.group(1))
    if not valid_range[0] <= year <= valid_range[1]:
        return None
    return year


def extract_years(
    text: str,
    *,
    valid_range: tuple[int, int] = YEAR_RANGE,
) -> list[int]:
    """Extract validated year integers from header-style text."""
    years: list[int] = []
    for match in TABLE_YEAR_RE.finditer(text):
        raw = match.group(1) or match.group(2)
        year = int(raw)
        if len(raw) == 2:
            year += 2000 if year < CENTURY_PIVOT else 1900
        if valid_range[0] <= year <= valid_range[1]:
            years.append(year)
    return years


def parse_numeric_year(
    value: str,
    *,
    valid_range: tuple[int, int] = YEAR_RANGE,
    century_pivot: int = CENTURY_PIVOT,
) -> int | None:
    """Parse a one- to four-digit numeric year token with century expansion."""
    match = NUMERIC_YEAR_RE.search(value.strip())
    if not match:
        return None
    year = int(match.group(1))
    if year < 100:
        year += 2000 if year < century_pivot else 1900
    if not valid_range[0] <= year <= valid_range[1]:
        return None
    return year


def month_name_to_index(name: str) -> int | None:
    """Return the month index (1-12) for a month name or alias."""
    normalized = ORDINAL_SUFFIX_RE.sub(r"\1", name)
    normalized = re.sub(r"[.,;:]+$", "", normalized).strip().lower()
    return _MONTH_NAME_TO_INDEX.get(normalized)


def _build_format_pattern(tokens: tuple[str, ...], separators: tuple[str, ...]) -> str:
    """Build a regex pattern from format tokens and separators."""
    parts: list[str] = []
    for idx, token in enumerate(tokens):
        if idx > 0:
            parts.append(_sep_pattern(separators[idx - 1]))
        if token == "MM_name":
            parts.append(rf"(?P<month>{MONTH_PATTERN})\.?")
        elif token == "DD":
            parts.append(rf"(?P<day>\d{{1,2}})(?:{ORDINAL_SUFFIX_PATTERN})?,?")
        elif token == "DD_num":
            parts.append(r"(?P<day>\d{1,2}),?")
        elif token == "MM":
            parts.append(r"(?P<month>\d{1,2})")
        elif token == "YYYY":
            parts.append(r"(?P<year>\d{4})")
    return rf"(?i)\b{''.join(parts)}\b"


def _sep_pattern(separator: str) -> str:
    escaped = re.escape(separator)
    return rf"\s*{escaped}\s*"


def _build_formats() -> tuple[DateFormat, ...]:
    formats = [
        (
            "month_day_year",
            ("MM_name", "DD", "YYYY"),
            (" ", ", "),
            100,
        ),
        (
            "month_day_year_nocomma",
            ("MM_name", "DD", "YYYY"),
            (" ", " "),
            90,
        ),
        (
            "day_month_year",
            ("DD_num", "MM_name", "YYYY"),
            (" ", " "),
            95,
        ),
        (
            "year_month_day_iso",
            ("YYYY", "MM", "DD"),
            ("-", "-"),
            110,
        ),
        (
            "year_month_day_name",
            ("YYYY", "MM_name", "DD"),
            (" ", " "),
            105,
        ),
        (
            "month_day_year_numeric",
            ("MM", "DD", "YYYY"),
            ("/", "/"),
            70,
        ),
        (
            "month_day_year_dash",
            ("MM", "DD", "YYYY"),
            ("-", "-"),
            60,
        ),
    ]
    return tuple(
        DateFormat(
            id=fmt_id,
            pattern=_build_format_pattern(tokens, separators),
            priority=priority,
        )
        for fmt_id, tokens, separators, priority in formats
    )


SEC_DATE_FORMATS = _build_formats()


def parse_date(
    text: str,
    *,
    formats: Sequence[DateFormat] = SEC_DATE_FORMATS,
) -> ParsedDate | None:
    """Parse a complete date string against known formats."""
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return None

    ordered = sorted(formats, key=lambda fmt: fmt.priority, reverse=True)
    for fmt in ordered:
        match = re.search(fmt.pattern, normalized)
        if not match:
            continue
        year_str = match.group("year")
        month_str = match.group("month")
        day_str = match.group("day")
        if not (year_str and month_str and day_str):
            continue
        year = int(year_str)
        if not YEAR_RANGE[0] <= year <= YEAR_RANGE[1]:
            continue
        month = month_name_to_index(month_str)
        if month is None:
            try:
                month = int(month_str)
            except ValueError:
                continue
            if not 1 <= month <= 12:
                continue
        day = int(ORDINAL_SUFFIX_RE.sub("", day_str))
        if not 1 <= day <= 31:
            continue
        components = DateComponents(year=year, month=month, day=day)
        if not components.valid():
            continue
        source = match.group(0).strip()
        return ParsedDate(format_id=fmt.id, source=source, components=components)
    return None


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


def _normalize_separators(text: str) -> str:
    """Collapse spaces around slash and dash date separators."""
    return re.sub(r"\s*/\s*", "/", re.sub(r"\s*-\s*", "-", text))


def _looks_like_date_fragment(parts: list[str]) -> bool:
    combined = " ".join(parts)
    if MONTH_RE.search(combined):
        return True
    return bool(
        re.search(r"\b\d{4}\b", combined) and ("/" in combined or "-" in combined)
    )


__all__ = [
    "CENTURY_PIVOT",
    "MONTH_ALIASES",
    "MONTH_NAMES",
    "MONTH_NAME_RE",
    "MONTH_PATTERN",
    "MONTH_RE",
    "MONTH_SUFFIX_RE",
    "ORDINAL_SUFFIX_PATTERN",
    "ORDINAL_SUFFIX_RE",
    "SEC_DATE_FORMATS",
    "TABLE_YEAR_RE",
    "YEAR_IN_TEXT_RE",
    "YEAR_RANGE",
    "YEAR_TOKEN_RE",
    "DateComponents",
    "DateFormat",
    "ParsedDate",
    "extract_years",
    "heal_date_fragments",
    "month_name_to_index",
    "parse_date",
    "parse_numeric_year",
    "parse_year_token",
]
