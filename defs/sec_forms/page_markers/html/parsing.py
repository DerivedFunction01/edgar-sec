"""Value parsing for page-marker candidates."""

from __future__ import annotations

import re

from ..candidates import roman_to_int
from ..constants import (
    _RE_LEADING_NUMBER,
    _RE_LETTER_NUMBER,
    _RE_TRAILING_NUMBER,
    _VALUE_RE,
)
from ..layout import candidate_template

_HAS_LABEL_SHAPE_RE = re.compile(r"\d|^[ivxlcdm]+$", re.IGNORECASE)
_YEAR_VALUE_MIN = 1900
_YEAR_VALUE_MAX = 2100


def _parse_value(
    text: str, *, allow_letter_number: bool = True
) -> tuple[int, str, str] | None:
    if len(text) > 80 and not any(char.isdigit() for char in text):
        return None
    parts = text.split()
    if not parts:
        return None
    cleaned = " ".join(parts)
    word_count = len(parts)
    match = _VALUE_RE.fullmatch(cleaned)
    if match is not None:
        value_text = match.group("value") or match.group("wrapped")
        value = int(value_text) if value_text.isdigit() else roman_to_int(value_text)
        if value is None or value <= 0:
            return None
        namespace = "arabic" if value_text.isdigit() else "roman"
        if (
            namespace == "arabic"
            and _YEAR_VALUE_MIN <= value <= _YEAR_VALUE_MAX
        ):
            return None
        return value, namespace, candidate_template(text)
    if allow_letter_number:
        letter_match = _RE_LETTER_NUMBER.fullmatch(cleaned)
        if letter_match is not None and (value := int(letter_match.group("page"))) > 0:
            return value, letter_match.group("prefix").upper(), candidate_template(text)
    if word_count <= 6:
        match_lead = _RE_LEADING_NUMBER.match(cleaned)
        if (
            match_lead is not None
            and _YEAR_VALUE_MIN
            <= (val := int(match_lead.group("value")))
            <= _YEAR_VALUE_MAX
        ):
            return None
        if match_lead is not None and val > 0:
            return val, "arabic", candidate_template(text)
        match_trail = _RE_TRAILING_NUMBER.match(cleaned)
        if (
            match_trail is not None
            and _YEAR_VALUE_MIN
            <= (val := int(match_trail.group("value")))
            <= _YEAR_VALUE_MAX
        ):
            return None
        if match_trail is not None and val > 0:
            return val, "arabic", candidate_template(text)
    return None


__all__ = ["_parse_value"]
