"""Financial magnitude and unit-scale parsing with anti-coincidence guardrails."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from functools import lru_cache, partial
import re

from edgar_sec.domain.forms.common.missing_values import COMMON_NUMERIC_NULL_POLICY
from edgar_sec.engine.tables.numeric_cells import CURRENCY_TOKEN_RE
from edgar_sec.foundation.regex.builder import build_alternation

NUMERIC_TOKEN_RE = re.compile(
    rf"^\s*\(?\s*(?:{CURRENCY_TOKEN_RE.pattern})?\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*(?:{CURRENCY_TOKEN_RE.pattern})?\s*\)?\b"
)
_PUNCT_STRIP_RE = re.compile(rf"[,\s]|(?:{CURRENCY_TOKEN_RE.pattern})")
_PREFIXES = ("up to", "approx.", "approx")
_SCALE_MULTIPLIERS: dict[str, int] = {
    "k": 1_000,
    "thousand": 1_000,
    "thousands": 1_000,
    "m": 1_000_000,
    "mm": 1_000_000,
    "million": 1_000_000,
    "millions": 1_000_000,
    "b": 1_000_000_000,
    "billion": 1_000_000_000,
    "billions": 1_000_000_000,
}

_SCALE_ALT = build_alternation(tuple(_SCALE_MULTIPLIERS.keys()))

_SCALED_NUMERIC_RE = re.compile(
    rf"^\s*([\$€£]?)\s*([\d,]+(?:\.\d+)?)\s*({_SCALE_ALT})?\s*$",
    re.IGNORECASE,
)
_SCHEMA_DECIMAL_RE = re.compile(
    r"^[+-]?(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?$"
)
_SCHEMA_INTEGER_RE = re.compile(r"^(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)$")
_SCHEMA_NUMERIC_TOKEN_RE = re.compile(r"(?<![\w.])([+-]?[0-9][0-9,]*(?:\.[0-9]+)?)")
_SPACED_THOUSANDS_SEPARATOR_RE = re.compile(r"(?<=\d),\s+(?=\d{3}(?:\D|$))")
_SCHEMA_UNIT_SUFFIX_ALT = build_alternation(
    (
        "shares of common stock",
        "shares of common",
        "common shares",
        "common stock",
        "shares",
        "share",
        "shs",
        "sh",
        "units",
        "unit",
    )
)
_SCHEMA_UNIT_SUFFIX_RE = re.compile(rf"(?i)\s*(?:{_SCHEMA_UNIT_SUFFIX_ALT})\.?$")
_SCHEMA_CURRENCY_RE = re.compile(CURRENCY_TOKEN_RE.pattern)
_PERCENT_TAIL_ALT = build_alternation(
    (
        r"\d+",
        r"refer\s+to.*",
        r"\([^)]*\)",
        r"\[[^\]]*\]",
        r"see\s+.*",
    ),
    auto_escape=False,
    compact=False,
)
_SCHEMA_PERCENT_RE = re.compile(
    rf"(?i)(?:%|\s+percent)(?:\s*(?:{_PERCENT_TAIL_ALT}))?\s*$"
)
_SCHEMA_TRAILING_MARKS_RE = re.compile(r"[*†‡.;+\-]+\s*$")
_SCHEMA_LEADING_MARKS_RE = re.compile(r"^(?:\[[*†‡\s]+\]|[*†‡\s]+)\s*")
_SCHEMA_SUB_BULLET_RE = re.compile(
    r"^(?:\[[*†‡\s]+\]|[*†‡\s]+)*(?:\([A-Za-z0-9]+\)|\[[A-Za-z0-9]+\])\s*"
)
_SCHEMA_ENTITY_PREFIX_RE = re.compile(r"^[^\d\n]{2,80}\s*[:\-–]\s*(?=[+-]?\d)")
_EUROPEAN_COMMA_DECIMAL_RE = re.compile(r"\d+,\d{1,2}$")
_SCHEMA_ZERO_DASHES_RE = re.compile(r"^-0-$")
_SCHEMA_FOOTNOTE_LABEL_ALT = build_alternation(
    (r"ITEM\s+\d+[A-Z]?", r"\d+", r"[A-Z]"),
    auto_escape=False,
    compact=False,
)
_SCHEMA_FOOTNOTE_REF_ALT = build_alternation(
    (
        rf"\(\s*(?:{_SCHEMA_FOOTNOTE_LABEL_ALT})\s*\)",
        r"\[\s*(?:\d+|[A-Z])\s*\]",
    ),
    auto_escape=False,
    compact=False,
)
_SCHEMA_FOOTNOTES_RE = re.compile(rf"(?i)(?:\s*(?:{_SCHEMA_FOOTNOTE_REF_ALT}))+\s*$")
_SEE_TARGETS_ALT = build_alternation(
    (
        "item",
        "footnote",
        "note",
        "exhibit",
        "instructions",
        "instruction",
        "remarks",
        "remark",
        "attached",
    ),
    auto_escape=True,
    compact=True,
)
_INCLUDES_TARGETS_ALT = build_alternation(
    ("shares", "options", "warrants"),
    auto_escape=True,
    compact=True,
)
_SCHEMA_DISCLAIMER_ALT = build_alternation(
    (
        r"beneficial\s+ownership\s+disclaimed",
        r"disclaimed\s+pursuant\s+to",
        r"disclaims\s+beneficial\s+ownership",
        r"pursuant\s+to\s+rule\s+13d-[34]",
        rf"see\s+(?:{_SEE_TARGETS_ALT})\b",
        r"refer\s+to\b",
        rf"includes?\s+(?:{_INCLUDES_TARGETS_ALT}|\d+)",
        rf"including\s+(?:{_INCLUDES_TARGETS_ALT}|\d+)",
        r"based\s+on\b",
    ),
    auto_escape=False,
    compact=True,
)
_SCHEMA_DISCLAIMER_RE = re.compile(
    rf"(?i)\s*(?:[([*†‡]+\s*)?(?:{_SCHEMA_DISCLAIMER_ALT}).*$"
)
_SCHEMA_APPROX_ALT = build_alternation(
    (
        r"approx(?:imately|\.)?",
        r"about",
        r"c\.",
    ),
    auto_escape=False,
    compact=True,
)
_SCHEMA_APPROX_RE = re.compile(rf"(?is)^\s*(?:{_SCHEMA_APPROX_ALT})\s*")
_SCHEMA_LEADING_PERCENT_RE = re.compile(
    r"(?is)^\s*([+-]?[0-9][0-9,]*(?:\.[0-9]+)?)\s*%(?:[,;]?(?:\s+.*)?)$"
)
_CLOSING_PERCENT_ALT = build_alternation(
    (
        r"less\s+than\s+5%",
        r"less\s+than\s+5\s+percent",
        r"<\s*5%",
        r"<\s*5\s*percent",
        r"less\s+than\s+5",
    ),
    auto_escape=False,
    compact=True,
)
_SCHEMA_CLOSING_PERCENT_RE = re.compile(rf"(?i)^\s*(?:{_CLOSING_PERCENT_ALT})\b")
_SCHEMA_LEADING_NUMERIC_RE = re.compile(
    r"(?s)^\s*([+-]?[0-9][0-9,]*(?:\.[0-9]+)?)(?:\s+.*)?$"
)
_UNRESOLVED_QUALIFIER_ALT = build_alternation(
    (
        r"and\s+more",
        r"or\s+more",
        r"and\s+additional",
        r"or\s+additional",
        r"and\s+others",
        r"plus\s+additional",
    ),
    auto_escape=False,
    compact=True,
)
_UNRESOLVED_QUALIFIER_RE = re.compile(rf"(?i)\b(?:{_UNRESOLVED_QUALIFIER_ALT})\b")


_HYPHENATED_ALPHA_RE = re.compile(r"[a-z0-9]-[a-z0-9]", re.IGNORECASE)
_SUB_BOX_LABEL_RE = re.compile(
    r"\(?[123]?\s*\([a-z]\)|^([123][a-z]|[a-z]\))\b", re.IGNORECASE
)
_DISALLOWED_CONTEXT_TERMS = (
    "rule",
    "form",
    "suite",
    "apt",
    "schedule",
    "cusip",
    "box",
)


def parse_scaled_number(token: str) -> int | float | None:
    """Parse financial numeric value with unit scale multipliers and guardrails."""
    clean = token.strip()
    if not clean:
        return None
    if _HYPHENATED_ALPHA_RE.search(clean) or _SUB_BOX_LABEL_RE.search(clean):
        return None
    lower = clean.lower()
    if any(k in lower for k in _DISALLOWED_CONTEXT_TERMS):
        return None

    match = _SCALED_NUMERIC_RE.match(clean)
    if not match:
        return None

    currency_sym, num_str, suffix = match.groups()
    normalized_num = num_str.replace(",", "")
    try:
        val = float(normalized_num)
    except ValueError:
        return None

    if suffix:
        s_lower = suffix.lower()
        if len(s_lower) == 1 and not currency_sym and "." not in normalized_num:
            return None
        mult = _SCALE_MULTIPLIERS.get(s_lower)
        if mult:
            val = val * mult

    if val.is_integer():
        return int(val)
    return val


@lru_cache(maxsize=2048)
def clean_numeric(text: str | None) -> float | int | None:
    """Extract and parse numeric amounts from formatted cell strings."""
    if text is None or COMMON_NUMERIC_NULL_POLICY.is_missing(text):
        return None
    cleaned = text.strip()
    lower = cleaned.lower()
    for prefix in _PREFIXES:
        if lower.startswith(prefix):
            cleaned = cleaned[len(prefix) :].strip()
            lower = cleaned.lower()
            break

    match = NUMERIC_TOKEN_RE.search(cleaned)
    if not match:
        return None

    raw_val = _PUNCT_STRIP_RE.sub("", match.group(1))
    is_negative = cleaned.startswith("(") and cleaned.endswith(")")
    try:
        if "." in raw_val:
            num = float(raw_val)
        else:
            num = int(raw_val)
        return -num if is_negative else num
    except ValueError:
        return None


def format_scaled_number_string(token: str) -> str | None:
    """Parse and format numeric token to canonical integer or decimal string."""
    val = parse_scaled_number(token)
    if val is None:
        return None
    if isinstance(val, int) or val.is_integer():
        return str(int(val))
    return f"{val:.2f}"


def normalize_schema_decimal(text: str | None) -> str | None:
    if not text:
        return None
    value = text.strip()
    if not _SCHEMA_DECIMAL_RE.fullmatch(value):
        return None
    try:
        number = Decimal(value.replace(",", ""))
    except InvalidOperation:
        return None
    if number.is_zero():
        return "0"
    return format(number, "f")


def normalize_schema_integer(text: str | None) -> str | None:
    if not text:
        return None
    value = text.strip()
    if not _SCHEMA_INTEGER_RE.fullmatch(value):
        return None
    return str(int(value.replace(",", "")))


def _strip_schema_policy(
    text: str,
    *,
    strip_currency: bool,
    strip_units: bool,
    strip_percent: bool,
    strip_footnotes: bool,
) -> str:
    value = text.strip()
    value = _SCHEMA_LEADING_MARKS_RE.sub("", value).strip()
    value = _SCHEMA_SUB_BULLET_RE.sub("", value).strip()
    value = _SCHEMA_TRAILING_MARKS_RE.sub("", value).strip()
    value = _SCHEMA_APPROX_RE.sub("", value).strip()
    if strip_footnotes:
        value = _SCHEMA_DISCLAIMER_RE.sub("", value).strip()
        value = _SCHEMA_FOOTNOTES_RE.sub("", value).strip()
    if strip_units:
        value = _SCHEMA_UNIT_SUFFIX_RE.sub("", value).strip()
    if strip_percent:
        if _SCHEMA_CLOSING_PERCENT_RE.search(value):
            return "0"
        value = _SCHEMA_PERCENT_RE.sub("", value).strip()
        if _EUROPEAN_COMMA_DECIMAL_RE.search(value):
            value = value.replace(",", ".")
    if strip_currency:
        value = _SCHEMA_CURRENCY_RE.sub("", value).strip()
    value = _SCHEMA_TRAILING_MARKS_RE.sub("", value).strip()
    return value


def normalize_schema_number(
    text: str | None,
    *,
    integer: bool,
    strip_currency: bool = False,
    strip_units: bool = False,
    strip_percent: bool = False,
    strip_footnotes: bool = False,
    extract_leading_number: bool = False,
    allow_accounting_negative: bool = False,
    allow_negative: bool = False,
    allow_integral_decimal: bool = False,
) -> str | None:
    if not text:
        return None
    value = _strip_schema_policy(
        text,
        strip_currency=strip_currency,
        strip_units=strip_units,
        strip_percent=strip_percent,
        strip_footnotes=strip_footnotes,
    )

    negative = value.startswith("(") and value.endswith(")")
    if negative:
        if not allow_accounting_negative:
            return None
        value = value[1:-1].strip()
    if _SCHEMA_ZERO_DASHES_RE.fullmatch(value):
        return "0"

    if integer and allow_integral_decimal:
        decimal = normalize_schema_decimal(value)
        if decimal is not None:
            try:
                number = Decimal(decimal)
            except InvalidOperation:
                return None
            normalized = (
                str(int(number)) if number == number.to_integral_value() else None
            )
        else:
            normalized = normalize_schema_integer(value)
    else:
        normalized = (
            normalize_schema_integer(value)
            if integer
            else normalize_schema_decimal(value)
        )
    if normalized is None and extract_leading_number:
        if _UNRESOLVED_QUALIFIER_RE.search(value):
            return None
        v_stripped = _SCHEMA_ENTITY_PREFIX_RE.sub("", value).strip()
        if v_stripped != value:
            v_val = _strip_schema_policy(
                v_stripped,
                strip_currency=strip_currency,
                strip_units=strip_units,
                strip_percent=strip_percent,
                strip_footnotes=strip_footnotes,
            )
            normalized = (
                normalize_schema_integer(v_val)
                if integer
                else normalize_schema_decimal(v_val)
            )
            if normalized is None:
                value = v_val
        if normalized is None and strip_percent:
            m_pct = _SCHEMA_LEADING_PERCENT_RE.match(value)
            if m_pct:
                token = m_pct.group(1).rstrip(",")
                normalized = (
                    normalize_schema_integer(token)
                    if integer
                    else normalize_schema_decimal(token)
                )
        if normalized is None:
            m = _SCHEMA_LEADING_NUMERIC_RE.match(value)
            if m:
                token = m.group(1).rstrip(",")
                normalized = (
                    normalize_schema_integer(token)
                    if integer
                    else normalize_schema_decimal(token)
                )
    if normalized is None:
        return None
    if negative and normalized != "0":
        normalized = f"-{normalized}"
    if not allow_negative and normalized.startswith("-"):
        return None
    return normalized


def normalize_schema_integral_decimal(
    text: str | None,
    *,
    strip_currency: bool = False,
    strip_units: bool = False,
    strip_percent: bool = False,
    strip_footnotes: bool = False,
    allow_accounting_negative: bool = False,
    allow_negative: bool = False,
) -> str | None:
    """Normalize a schema decimal that may be written as an integral decimal."""
    if not text:
        return None
    value = _strip_schema_policy(
        text,
        strip_currency=strip_currency,
        strip_units=strip_units,
        strip_percent=strip_percent,
        strip_footnotes=strip_footnotes,
    )
    negative = value.startswith("(") and value.endswith(")")
    if negative:
        if not allow_accounting_negative:
            return None
        value = value[1:-1].strip()
    if _SCHEMA_ZERO_DASHES_RE.fullmatch(value):
        return "0"
    decimal = normalize_schema_decimal(value)
    if decimal is None:
        return None
    number = Decimal(decimal)
    normalized = str(int(number)) if number == number.to_integral_value() else decimal
    if negative and normalized != "0":
        normalized = f"-{normalized}"
    if not allow_negative and normalized.startswith("-"):
        return None
    return normalized


def normalize_schema_integer_value(text: str | None, **policy: bool) -> int | None:
    normalized = normalize_schema_number(text, integer=True, **policy)
    return int(normalized) if normalized is not None else None


normalize_integer_stripping_units = partial(
    normalize_schema_integer_value, strip_units=True
)
normalize_decimal_stripping_currency = partial(
    normalize_schema_number,
    integer=False,
    strip_currency=True,
    allow_accounting_negative=True,
    allow_negative=True,
)


def extract_schema_number(text: str) -> str | None:
    normalized_text = _SPACED_THOUSANDS_SEPARATOR_RE.sub(",", text)
    match = _SCHEMA_NUMERIC_TOKEN_RE.search(normalized_text)
    if match is None:
        return None
    number = match.group(1)
    negative = text.strip().startswith("(") and text.strip().endswith(")")
    if negative:
        number = f"-{number.lstrip('+-')}"
    return normalize_schema_number(number, integer=False, allow_negative=negative)


def extract_schema_number_or_token(text: str) -> str | None:
    """Return the policy-conformant number, or the raw token the policy rejects."""
    normalized = extract_schema_number(text)
    if normalized is not None:
        return normalized
    match = _SCHEMA_NUMERIC_TOKEN_RE.search(text)
    return match.group(1) if match is not None else None


__all__ = [
    "NUMERIC_TOKEN_RE",
    "clean_numeric",
    "extract_schema_number",
    "extract_schema_number_or_token",
    "format_scaled_number_string",
    "normalize_schema_decimal",
    "normalize_schema_integer",
    "normalize_schema_integer_value",
    "normalize_schema_integral_decimal",
    "normalize_schema_number",
    "parse_scaled_number",
]
