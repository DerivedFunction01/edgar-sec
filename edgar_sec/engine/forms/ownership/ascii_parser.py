"""Main ASCII state machine parser for historical Form 4 filings."""

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

_FORM4_MARKER_TERMS = (
    r"\bFORM\s*4\b",
    r"STATEMENT OF CHANGES IN BENEFICIAL OWNERSHIP",
    r"<TYPE>4",
)
_FORM4_MARKER_ALT = build_alternation(_FORM4_MARKER_TERMS, auto_escape=False)
_FORM4_MARKER_RE = re.compile(_FORM4_MARKER_ALT, re.IGNORECASE)


def parse_ascii_form4(
    raw_text: str, reference_year: int | None = None
) -> OwnershipSections | None:
    """Parse Form 4 ASCII text into typed OwnershipSections."""
    if not _FORM4_MARKER_RE.search(raw_text):
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


__all__ = ["parse_ascii_form4"]
