"""Modular date parsing and healing for SEC filings."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime

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

_RE_WHITESPACE = re.compile(r"\s+")
_RE_SLASH_SEP = re.compile(r"\s*/\s*")
_RE_DASH_SEP = re.compile(r"\s*-\s*")
_RE_DATE_FRAGMENT = re.compile(
    r"(?:\d{1,4}(?:st|nd|rd|th)?|[,./-])(?:\s*[,./-]?\s*)?",
    re.IGNORECASE,
)
_RE_YEAR_IN_TEXT = re.compile(r"\b\d{4}\b")
_RE_TRAILING_PUNCT = re.compile(r"[.,;:]+$")


def _current_system_year() -> int:
    return datetime.now(UTC).year


_SYSTEM_YEAR = _current_system_year()
DEFAULT_YEAR_UPPER_BOUND = max(2100, _SYSTEM_YEAR + 50)
YEAR_RANGE = (1900, DEFAULT_YEAR_UPPER_BOUND)
CENTURY_PIVOT = 80


def is_valid_year(year: int, valid_range: tuple[int, int] = YEAR_RANGE) -> bool:
    """Return whether an integer year falls within the valid system year range."""
    return valid_range[0] <= year <= valid_range[1]


def is_year_token(value: str, valid_range: tuple[int, int] = YEAR_RANGE) -> bool:
    """Return whether a string represents a standalone 4-digit calendar year."""
    v = value.strip()
    return (
        len(v) == 4 and v.isdigit() and is_valid_year(int(v), valid_range=valid_range)
    )


YEAR_TOKEN_PATTERN = build_alternation(
    [r"19[0-9]{2}", r"[2-9][0-9]{3}"], auto_escape=False
)
YEAR_TOKEN_RE = re.compile(rf"^\b({YEAR_TOKEN_PATTERN})\b$")
YEAR_IN_TEXT_RE = re.compile(r"\b(\d{4})\b")
NUMERIC_YEAR_RE = re.compile(r"\b(\d{2,4})\b")
TABLE_YEAR_RE = re.compile(
    build_alternation(
        [r"(?:\d{1,2}/)+(\d{2,4})", r"\b(\d{4})\b", r"['’](\d{2})\b"],
        auto_escape=False,
    )
)

# Multi-column period/year header row (e.g. "   2004       2003       2002   " or "   Q1 2004   Q1 2003   ")
_Q_TOKEN_PAT = rf"Q[1-4]\s+{YEAR_TOKEN_PATTERN}"
_DATE_TOKEN_PAT = rf"(?:{MONTH_PATTERN})\s+\d{{1,2}},?\s+{YEAR_TOKEN_PATTERN}"
_PERIOD_TOKEN_PAT = build_alternation(
    [YEAR_TOKEN_PATTERN, _Q_TOKEN_PAT, _DATE_TOKEN_PAT],
    auto_escape=False,
    compact=False,
)
_PERIOD_HEADER_SUFFIX_PAT = build_alternation(
    [_PERIOD_TOKEN_PAT, MONTH_PATTERN, r"Q[1-4]"],
    auto_escape=False,
    compact=False,
)

COLUMN_YEAR_ROW_RE = re.compile(
    rf"^\s*(?:{_PERIOD_TOKEN_PAT})(?:\s+(?:{_PERIOD_HEADER_SUFFIX_PAT}).*)?\s*$",
    re.IGNORECASE,
)
RE_FULL_DATE = re.compile(rf"\b(?:{_DATE_TOKEN_PAT})\b", re.IGNORECASE)

_PERIOD_SPAN_WORDS = build_alternation(
    [
        "three months",
        "six months",
        "nine months",
        "fiscal year",
        "fiscal",
        "year",
        "years",
        "quarter",
        "quarters",
        "period",
        "periods",
    ],
    auto_escape=True,
    compact=True,
)
_PERIOD_SUBHEADING_PATTERNS = [
    rf"(?:{_PERIOD_SPAN_WORDS})\s+(?:ended\s+)?{YEAR_TOKEN_PATTERN}",
    rf"(?:{_PERIOD_SPAN_WORDS})\s+(?:ended\s+)?Q[1-4]",
    rf"Q[1-4]\s+{YEAR_TOKEN_PATTERN}",
]
PERIOD_SUBHEADING_PAT = build_alternation(
    _PERIOD_SUBHEADING_PATTERNS, auto_escape=False, compact=False
)
PERIOD_SUBHEADING_RE = re.compile(
    rf"^\s*(?:{PERIOD_SUBHEADING_PAT})\s*:?\s*$", re.IGNORECASE
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
    pattern: re.Pattern[str]
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


def expand_2digit_year(
    year: int,
    *,
    reference_year: int | None = None,
    lookback_years: int = 80,
    century_pivot: int | None = None,
) -> int:
    """Expand a 1- or 2-digit year using a dynamic rolling window relative to a reference year."""
    if year >= 100:
        return year
    anchor = _SYSTEM_YEAR if reference_year is None else reference_year
    if century_pivot is not None:
        current_century = (anchor // 100) * 100
        prev_century = current_century - 100
        return (
            (current_century + year) if year < century_pivot else (prev_century + year)
        )

    base_year = anchor - lookback_years
    base_century = (base_year // 100) * 100
    candidate = base_century + year
    if candidate < base_year:
        candidate += 100
    return candidate


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
    if not is_valid_year(year, valid_range=valid_range):
        return None
    return year


def extract_years(
    text: str,
    *,
    reference_year: int | None = None,
    valid_range: tuple[int, int] = YEAR_RANGE,
    lookback_years: int = 80,
    century_pivot: int | None = None,
) -> list[int]:
    """Extract validated year integers from header-style text."""
    years: list[int] = []
    for match in TABLE_YEAR_RE.finditer(text):
        raw = next((g for g in match.groups() if g is not None), None)
        if not raw:
            continue
        year = int(raw)
        if len(raw) <= 2:
            year = expand_2digit_year(
                year,
                reference_year=reference_year,
                lookback_years=lookback_years,
                century_pivot=century_pivot,
            )
        if is_valid_year(year, valid_range=valid_range):
            years.append(year)
    return years


def parse_numeric_year(
    value: str,
    *,
    reference_year: int | None = None,
    valid_range: tuple[int, int] = YEAR_RANGE,
    lookback_years: int = 80,
    century_pivot: int | None = None,
) -> int | None:
    """Parse a one- to four-digit numeric year token with century expansion."""
    match = NUMERIC_YEAR_RE.search(value.strip())
    if not match:
        return None
    year = int(match.group(1))
    if year < 100:
        year = expand_2digit_year(
            year,
            reference_year=reference_year,
            lookback_years=lookback_years,
            century_pivot=century_pivot,
        )
    if not is_valid_year(year, valid_range=valid_range):
        return None
    return year


def month_name_to_index(name: str) -> int | None:
    """Return the month index (1-12) for a month name or alias."""
    normalized = ORDINAL_SUFFIX_RE.sub(r"\1", name)
    normalized = _RE_TRAILING_PUNCT.sub("", normalized).strip().lower()
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
            pattern=re.compile(_build_format_pattern(tokens, separators)),
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
    normalized = _RE_WHITESPACE.sub(" ", text).strip()
    if not normalized:
        return None

    ordered = sorted(formats, key=lambda fmt: fmt.priority, reverse=True)
    for fmt in ordered:
        match = fmt.pattern.search(normalized)
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


def _is_date_fragment(text: str) -> bool:
    """Return whether a line contains only one fragment of a date."""
    normalized = text.strip()
    if not normalized:
        return False
    if MONTH_RE.fullmatch(normalized.rstrip(".")):
        return True
    return bool(_RE_DATE_FRAGMENT.fullmatch(normalized))


def _normalize_separators(text: str) -> str:
    """Collapse spaces around slash and dash date separators."""
    return _RE_SLASH_SEP.sub("/", _RE_DASH_SEP.sub("-", text))


# One ownership point for "does this text contain a full SEC date?".
# Composed from the format registry so new formats join automatically
# instead of consumers hand-rolling date-shape alternations. Patterns are
# matched individually because each carries its own named groups.


def contains_date(text: str) -> bool:
    """Return whether ``text`` contains a recognizable SEC date."""
    normalized = _RE_WHITESPACE.sub(" ", text).strip()
    return any(fmt.pattern.search(normalized) for fmt in SEC_DATE_FORMATS)


def _looks_like_date_fragment(parts: list[str]) -> bool:
    combined = " ".join(parts)
    if MONTH_RE.search(combined):
        return True
    return bool(
        _RE_YEAR_IN_TEXT.search(combined) and ("/" in combined or "-" in combined)
    )


__all__ = [
    "CENTURY_PIVOT",
    "COLUMN_YEAR_ROW_RE",
    "MONTH_ALIASES",
    "MONTH_NAMES",
    "MONTH_NAME_RE",
    "MONTH_PATTERN",
    "MONTH_RE",
    "MONTH_SUFFIX_RE",
    "ORDINAL_SUFFIX_PATTERN",
    "ORDINAL_SUFFIX_RE",
    "PERIOD_SUBHEADING_PAT",
    "PERIOD_SUBHEADING_RE",
    "RE_FULL_DATE",
    "SEC_DATE_FORMATS",
    "TABLE_YEAR_RE",
    "YEAR_IN_TEXT_RE",
    "YEAR_RANGE",
    "YEAR_TOKEN_PATTERN",
    "YEAR_TOKEN_RE",
    "DateComponents",
    "DateFormat",
    "ParsedDate",
    "contains_date",
    "expand_2digit_year",
    "extract_years",
    "heal_date_fragments",
    "is_valid_year",
    "is_year_token",
    "month_name_to_index",
    "parse_date",
    "parse_numeric_year",
    "parse_year_token",
]
