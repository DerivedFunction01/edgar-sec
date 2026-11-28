"""Related-party seat: the priced formation seat for
related-party tables whose own score stays under the floor.
Final compete_filing pass: an unclaimed geometry seats on
its own heading or stub form over an amount-bearing grid.
"""

from __future__ import annotations

from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_scoring import (
    ClaimGroup,
    CompetitionResult,
)
from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_text import (
    GeometryText,
)
from edgar_sec.engine.tables.extraction.core.term_index import TermEntry, TermIndex
from edgar_sec.engine.tables.extraction.core.text.normalize import normalize_text
from edgar_sec.engine.tables.extraction.seats.seat_application import (
    seat_applier,
    seat_role,
)
from edgar_sec.engine.tables.extraction.vetoes.term_vetoes import term_veto_hits

FAMILY = "related_party"

# Priced over the re-earned expansion population at the
# packet tree: the FULLB composition (corroborated guard
# exceptions, affiliate leg, prose guard, row bound 48).
HEADING_PHRASES = ("related part", "related person")
RELATIONAL_HEADING_PHRASES = ("from affiliates", "to affiliates")
TITLE_PHRASES = ("related part", "related person", "affiliate")
STUB_PARTY_PHRASES = (
    "related part",
    "related person",
    "affiliate",
    "due from",
    "due to",
)
RELATIONSHIP_PHRASE = "relationship with"
RELATIONSHIP_CONTEXT = ("subsidiary", "parent compan")
CAPTION_VETO_TERMS = frozenset({"years", "period"})
PROSE_HEADING_WORDS = 53
MIN_DATA_ROWS = 2
MIN_NUMERIC_CELLS = 2
MAX_DATA_ROWS = 48
MAX_STUBS = 20

# Single-pass evidence matching: one compiled matcher per
# channel text, a single scan reporting every evidence
# class the channel carries, the legs reading the hit
# sets. Every index key is the verbatim priced string,
# so admissions are preserved by construction.
_HEADING_INDEX = TermIndex(
    [TermEntry(phrase, "heading") for phrase in HEADING_PHRASES]
    + [TermEntry(phrase, "relational") for phrase in RELATIONAL_HEADING_PHRASES]
)
_TITLE_INDEX = TermIndex(
    [TermEntry(phrase, "title") for phrase in TITLE_PHRASES]
    + [TermEntry(RELATIONSHIP_PHRASE, "relationship")]
)
_STUB_INDEX = TermIndex(TermEntry(phrase, "stub") for phrase in STUB_PARTY_PHRASES)
_LEADIN_INDEX = TermIndex(TermEntry(term, "context") for term in RELATIONSHIP_CONTEXT)


def _heading_text(geometry: GeometryText) -> str:
    """The geometry's own heading channels: lead title,
    caption, and the leadin's first line."""
    first_line = ""
    for line in geometry.leadin.splitlines():
        if line.strip():
            first_line = line
            break
    parts = (geometry.lead_title, geometry.caption, first_line)
    return normalize_text(" ".join(part for part in parts if part))


def _amounts(geometry: GeometryText) -> bool:
    """An amount-bearing grid inside the priced size bound."""
    return (
        geometry.data_rows >= MIN_DATA_ROWS
        and geometry.numeric_cells >= MIN_NUMERIC_CELLS
        and geometry.data_rows <= MAX_DATA_ROWS
        and len(geometry.stubs) <= MAX_STUBS
    )


def _hard_terms(hits: dict) -> set[str] | None:
    """The geometry's hard veto terms for this family."""
    hard = hits.get("hard")
    if hard is None:
        return None
    if isinstance(hard, str):
        return {hard}
    return {str(term) for term in hard}


def _seat_one(geometry: GeometryText, result: CompetitionResult) -> CompetitionResult:
    """Seat related_party on one unclaimed geometry, or don't."""
    if result.claims:
        return result
    heading = _heading_text(geometry)
    heading_hits = _HEADING_INDEX.scan(heading)
    stub_hits = _STUB_INDEX.scan(
        "\n".join(normalize_text(stub) for stub in geometry.stubs)
    )
    # The table's own heading names the related-party
    # subject; a prose-blob heading names nothing.
    heading_leg = (
        len(heading.split()) <= PROSE_HEADING_WORDS and "heading" in heading_hits
    )
    stub_any = "stub" in stub_hits
    corroborated = heading_leg and stub_any
    separator = geometry.summary_separator
    if separator is not None and separator.fired and not corroborated:
        return result
    terms = _hard_terms(term_veto_hits(geometry).get(FAMILY) or {})
    if terms is not None and not (terms <= CAPTION_VETO_TERMS and corroborated):
        return result
    if not _amounts(geometry):
        return result
    title_hits = _TITLE_INDEX.scan(normalize_text(geometry.note_title or ""))
    stub_leg = "title" in title_hits and stub_any
    affiliate_leg = (
        "heading" in heading_hits or "relational" in heading_hits
    ) and stub_any
    relationship_leg = "relationship" in title_hits and "context" in _LEADIN_INDEX.scan(
        normalize_text(geometry.leadin)
    )
    if not (heading_leg or stub_leg or relationship_leg or affiliate_leg):
        return result
    score = result.scores.get(FAMILY)
    role = seat_role(geometry)
    group = ClaimGroup(
        family=FAMILY,
        score=score.total if score is not None else 0.0,
        state="reach",
        role=role,
        channels=dict(score.by_channel) if score is not None else {},
        veto_flags=(),
        explained_foreign=0.0,
    )
    return CompetitionResult(
        claims=(FAMILY,),
        contested=result.contested,
        scores=result.scores,
        foreign_explained=result.foreign_explained,
        groups=result.groups + (group,),
    )


apply_related_party_seat = seat_applier(_seat_one, "apply_related_party_seat")
