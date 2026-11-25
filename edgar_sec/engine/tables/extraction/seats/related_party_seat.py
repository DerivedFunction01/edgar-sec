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


def _heading_leg(geometry: GeometryText) -> bool:
    """The table's own heading names the related-party
    subject; a prose-blob heading names nothing."""
    heading = _heading_text(geometry)
    if len(heading.split()) > PROSE_HEADING_WORDS:
        return False
    return any(phrase in heading for phrase in HEADING_PHRASES)


def _stub_any(geometry: GeometryText) -> bool:
    """Any stub carries a party form, whatever its title."""
    stubs = [normalize_text(stub) for stub in geometry.stubs]
    return any(phrase in stub for stub in stubs for phrase in STUB_PARTY_PHRASES)


def _stub_leg(geometry: GeometryText) -> bool:
    """Party-form stubs under a related-party note title."""
    title = normalize_text(geometry.note_title or "")
    if not any(phrase in title for phrase in TITLE_PHRASES):
        return False
    stubs = [normalize_text(stub) for stub in geometry.stubs]
    return any(phrase in stub for stub in stubs for phrase in STUB_PARTY_PHRASES)


def _relationship_leg(geometry: GeometryText) -> bool:
    """A relationship-titled note whose prose names the
    parent/subsidiary relation the table prices."""
    title = normalize_text(geometry.note_title or "")
    if RELATIONSHIP_PHRASE not in title:
        return False
    lead = normalize_text(geometry.leadin)
    return any(term in lead for term in RELATIONSHIP_CONTEXT)


def _affiliate_leg(geometry: GeometryText) -> bool:
    """A relational affiliate heading over party-form stubs."""
    heading = _heading_text(geometry)
    phrases = HEADING_PHRASES + RELATIONAL_HEADING_PHRASES
    return any(phrase in heading for phrase in phrases) and _stub_any(geometry)


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
    corroborated = _heading_leg(geometry) and _stub_any(geometry)
    separator = geometry.summary_separator
    if separator is not None and separator.fired and not corroborated:
        return result
    terms = _hard_terms(term_veto_hits(geometry).get(FAMILY) or {})
    if terms is not None and not (terms <= CAPTION_VETO_TERMS and corroborated):
        return result
    if not _amounts(geometry):
        return result
    if not (
        _heading_leg(geometry)
        or _stub_leg(geometry)
        or _relationship_leg(geometry)
        or _affiliate_leg(geometry)
    ):
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
