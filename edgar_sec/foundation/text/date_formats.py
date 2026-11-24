"""SEC date format table: pattern builders and ordered format sets."""

from __future__ import annotations

from dataclasses import dataclass
import re

from edgar_sec.foundation.text.date_patterns import (
    MONTH_PATTERN,
    ORDINAL_SUFFIX_PATTERN,
)


@dataclass(frozen=True, slots=True)
class DateFormat:
    id: str
    pattern: re.Pattern[str]
    priority: int = 0


def _sep_pattern(separator: str) -> str:
    s = separator.strip()
    if not s:
        return r"\s+" if separator else r"\s*"
    escaped = re.escape(s)
    return rf"\s*{escaped}\s*"


def _build_format_pattern(tokens: tuple[str, ...], separators: tuple[str, ...]) -> str:
    parts: list[str] = []
    for idx, token in enumerate(tokens):
        if idx > 0 and idx - 1 < len(separators):
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
        elif token == "YY":
            parts.append(r"(?P<year>\d{2})")
    prefix = r"(?<![\d/-])" if tokens and tokens[0] in ("MM", "DD", "DD_num") else r""
    return rf"(?i){prefix}\b{''.join(parts)}\b"


def _build_formats() -> tuple[DateFormat, ...]:
    formats = [
        (
            "month_day_year",
            ("MM_name", "DD", "YYYY"),
            (" ", ","),
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
            ("DD", "MM_name", "YYYY"),
            (" ", " "),
            95,
        ),
        (
            "day_month_year_dash",
            ("DD", "MM_name", "YYYY"),
            ("-", "-"),
            94,
        ),
        (
            "year_month_day_iso",
            ("YYYY", "MM", "DD"),
            ("-", "-"),
            110,
        ),
        (
            "year_month_day_compact",
            ("YYYY", "MM", "DD"),
            ("", ""),
            108,
        ),
        (
            "year_month_day_name",
            ("YYYY", "MM_name", "DD"),
            (" ", " "),
            105,
        ),
        (
            "month_year_comma",
            ("MM_name", "YYYY"),
            (",",),
            85,
        ),
        (
            "month_year_space",
            ("MM_name", "YYYY"),
            (" ",),
            80,
        ),
        (
            "month_year_slash",
            ("MM_name", "YYYY"),
            ("/",),
            78,
        ),
        (
            "month_year_numeric",
            ("MM", "YYYY"),
            ("/",),
            65,
        ),
        (
            "month_year_numeric_dash",
            ("MM", "YYYY"),
            ("-",),
            54,
        ),
        (
            "month_day_year_numeric",
            ("MM", "DD", "YYYY"),
            ("/", "/"),
            70,
        ),
        (
            "day_month_year_numeric",
            ("DD_num", "MM", "YYYY"),
            ("/", "/"),
            68,
        ),
        (
            "month_day_year_dash",
            ("MM", "DD", "YYYY"),
            ("-", "-"),
            60,
        ),
        (
            "month_day_year_dot",
            ("MM", "DD", "YYYY"),
            (".", "."),
            58,
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


def _build_2digit_formats() -> tuple[DateFormat, ...]:
    formats = [
        (
            "month_day_year_name_2digit",
            ("MM_name", "DD", "YY"),
            (" ", ","),
            55,
        ),
        (
            "month_day_year_name_2digit_nocomma",
            ("MM_name", "DD", "YY"),
            (" ", " "),
            50,
        ),
        (
            "day_month_year_dash_2digit",
            ("DD_num", "MM_name", "YY"),
            ("-", "-"),
            48,
        ),
        (
            "month_day_year_2digit",
            ("MM", "DD", "YY"),
            ("/", "/"),
            45,
        ),
        (
            "month_day_year_dash_2digit",
            ("MM", "DD", "YY"),
            ("-", "-"),
            40,
        ),
        (
            "month_day_year_dot_2digit",
            ("MM", "DD", "YY"),
            (".", "."),
            38,
        ),
        (
            "month_year_2digit_comma",
            ("MM_name", "YY"),
            (",",),
            35,
        ),
        (
            "month_year_2digit_space",
            ("MM_name", "YY"),
            (" ",),
            30,
        ),
        (
            "day_month_year_numeric_dash_2digit",
            ("DD_num", "MM", "YY"),
            ("-", "-"),
            36,
        ),
        (
            "day_month_year_numeric_2digit",
            ("DD_num", "MM", "YY"),
            ("/", "/"),
            37,
        ),
        (
            "month_year_numeric_2digit",
            ("MM", "YY"),
            ("/",),
            25,
        ),
        (
            "month_year_numeric_dash_2digit",
            ("MM", "YY"),
            ("-",),
            22,
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


SEC_DATE_FORMATS = tuple(
    sorted(_build_formats(), key=lambda fmt: fmt.priority, reverse=True)
)


ALL_SEC_DATE_FORMATS = SEC_DATE_FORMATS + _build_2digit_formats()


_ALL_SEC_DATE_FORMATS_ORDERED = tuple(
    sorted(ALL_SEC_DATE_FORMATS, key=lambda fmt: fmt.priority, reverse=True)
)


__all__ = [
    "SEC_DATE_FORMATS",
    "DateFormat",
]
