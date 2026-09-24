"""SEC Regulation S-K Item 601 / Item 15 & 16 Exhibit Index concepts."""

from __future__ import annotations

import re

from defs.regex import build_alternation
from defs.taxonomy.tables.shapes import ShapeConstraint
from defs.taxonomy.tables.specs import (
    RepairPolicy,
    TableFamilySpec,
    TableScope,
    build_ngram_tier,
)
from defs.text.bow import LexicalEvidencePack, compile_evidence_pack

EXHIBIT_INDEX_STATUTORY_PHRASES: dict[str, tuple[str, ...]] = {
    "P1_exhibit_number": (
        "exhibit number",
        "exhibit no.",
        "exhibit no",
        "exhibit",
    ),
    "P2_description": (
        "exhibit description",
        "description of exhibit",
        "description of exhibits",
        "title of document",
    ),
    "P3_incorporated": (
        "incorporated by reference",
        "incorporation by reference",
        "incorporated herein by reference",
    ),
    "P4_filed_herewith": (
        "filed herewith",
        "furnished herewith",
        "filed / furnished herewith",
        "filed/furnished herewith",
    ),
    "P5_filing_date": (
        "filing date",
        "date of filing",
        "date filed",
    ),
    "P6_period_ending": (
        "period ending",
        "period ended",
        "applicable period",
        "file number",
        "commission file number",
        "commission file no.",
    ),
    "P7_compensatory_plan": (
        "management contract",
        "compensatory plan",
        "compensatory plan or arrangement",
    ),
}

CANONICAL_EXHIBIT_HEADERS: tuple[str, ...] = (
    "Exhibit Number",
    "Exhibit Description",
    "Filed Herewith",
    "Form",
    "Period Ending",
    "Exhibit",
    "Filing Date",
)

_exhibit_phrases: tuple[str, ...] = tuple(
    phrase for phrases in EXHIBIT_INDEX_STATUTORY_PHRASES.values() for phrase in phrases
)

# Compiled pattern matching standard exhibit index numbers (e.g. 10.1, 10(a), 4.2)
RE_EXHIBIT_NUMBER = re.compile(
    r"\b\d{1,2}(?:\.\d{1,2}|\([a-z0-9]+\))\b",
    re.IGNORECASE,
)

# Compiled alternation matching statutory exhibit phrases and Item 601 footnote cues
RE_EXHIBIT_STATUTORY_PHRASE = re.compile(
    rf"\b(?:{build_alternation(_exhibit_phrases, auto_escape=True, sort_longest_first=True)})\b",
    re.IGNORECASE,
)

_EXHIBIT_INDEX_PACK = compile_evidence_pack(
    LexicalEvidencePack(
        name="exhibit_index",
        tiers=tuple(
            t
            for t in (
                build_ngram_tier(
                    "statutory_phrases",
                    _exhibit_phrases,
                    priority=10,
                    value=2,
                    min_distinct_hits=2,
                ),
            )
            if t is not None
        ),
    )
)

EXHIBIT_INDEX_SPEC = TableFamilySpec(
    name="exhibit_index",
    shape=ShapeConstraint(min_rows=3, min_cols=2),
    evidence_pack=_EXHIBIT_INDEX_PACK,
    repair_policy=RepairPolicy.FAMILY_TEMPLATE,
    candidate_default_scope=TableScope.BODY,
)

__all__ = [
    "CANONICAL_EXHIBIT_HEADERS",
    "EXHIBIT_INDEX_SPEC",
    "EXHIBIT_INDEX_STATUTORY_PHRASES",
    "RE_EXHIBIT_NUMBER",
    "RE_EXHIBIT_STATUTORY_PHRASE",
]
