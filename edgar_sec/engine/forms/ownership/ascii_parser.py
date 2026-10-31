"""Main ASCII state machine parser for historical ownership filings."""

from __future__ import annotations

import re

from edgar_sec.engine.forms.ownership.ascii_header import (
    extract_ascii_header_and_signatures,
)
from edgar_sec.engine.forms.ownership.ascii_shape import (
    AsciiShape,
    detect_ascii_shape,
)
from edgar_sec.engine.forms.ownership.ascii_tables import (
    extract_ascii_tables_and_footnotes,
)
from edgar_sec.engine.forms.ownership.sections import OwnershipSections
from edgar_sec.foundation.regex.builder import build_alternation

_MARKER_TERMS: dict[str, tuple[str, ...]] = {
    "3": (
        r"\bFORM\s*3\b",
        r"INITIAL STATEMENT OF BENEFICIAL OWNERSHIP",
        r"<TYPE>3",
    ),
    "4": (
        r"\bFORM\s*4\b",
        r"STATEMENT OF CHANGES IN BENEFICIAL OWNERSHIP",
        r"<TYPE>4",
    ),
    "5": (
        r"\bFORM\s*5\b",
        r"ANNUAL STATEMENT OF CHANGES IN BENEFICIAL OWNERSHIP",
        r"<TYPE>5",
    ),
}
_MARKER_RES: dict[str, re.Pattern[str]] = {
    family: re.compile(build_alternation(terms, auto_escape=False), re.IGNORECASE)
    for family, terms in _MARKER_TERMS.items()
}


def parse_ascii_ownership(
    raw_text: str, family: str, reference_year: int | None = None
) -> OwnershipSections | None:
    """Parse an ASCII ownership filing of the given family into sections."""
    marker_re = _MARKER_RES.get(family)
    if marker_re is None or not marker_re.search(raw_text):
        return None

    shape = detect_ascii_shape(raw_text)

    boxes_1_to_7, signatures = extract_ascii_header_and_signatures(
        raw_text, reference_year
    )
    table_i, table_ii, footnotes = extract_ascii_tables_and_footnotes(raw_text, shape)

    if boxes_1_to_7 is None and table_i is None and table_ii is None:
        return None

    return OwnershipSections(
        boxes_1_to_7=boxes_1_to_7,
        table_i=table_i,
        table_ii=table_ii,
        signatures=signatures,
        footnotes=footnotes,
        unparsed=[],
    )


__all__ = ["parse_ascii_ownership"]
