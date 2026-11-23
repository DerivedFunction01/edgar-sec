"""Cover seat: the priced formation seat for cover pages the
chain only refuses.

Final compete_filing pass: an unclaimed geometry seats
cover_layout on the cover's own front-matter evidence.
"""

from __future__ import annotations

from edgar_sec.domain.forms.common.checkmarks import COVER_LAYOUT_GLYPHS
from edgar_sec.domain.forms.common.vocabulary import COVER_LAYOUT_TERMS
from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_scoring import (
    ClaimGroup,
    CompetitionResult,
)
from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_text import (
    GeometryText,
)
from edgar_sec.engine.tables.extraction.core.text.normalize import normalize_text

FAMILY = "cover_layout"

# Priced by the cover-layout trade curve over the frame: the
# lead cell (29 conversions, 0 classified false adds) and the
# boundary arm (2 conversions, 0 classified false adds).
GRID_ROWS_MAX = 8
BOUNDARY_TABLE_INDEX_MAX = 6


def _cover_text(geometry: GeometryText) -> str:
    """The geometry's cover-side text, channels joined once."""
    parts = (
        geometry.stub_text,
        " ".join(geometry.headers),
        geometry.caption,
        geometry.leadin,
        geometry.grid_text,
    )
    return normalize_text(" ".join(part for part in parts if part))


def _vocab_count(text: str) -> int:
    """Distinct cover-vocabulary terms present in the text."""
    return sum(1 for term in COVER_LAYOUT_TERMS if term in text)


def _checkbox(text: str, geometry: GeometryText) -> bool:
    """A ballot glyph on the grid, or the check-mark instruction."""
    if any(glyph in geometry.grid_text for glyph in COVER_LAYOUT_GLYPHS):
        return True
    return "check mark" in text or "check the appropriate box" in text


def _seat_one(geometry: GeometryText, result: CompetitionResult) -> CompetitionResult:
    """Seat cover_layout on one unclaimed geometry, or don't."""
    if result.claims:
        return result
    if geometry.grid_rows > GRID_ROWS_MAX:
        return result
    text = _cover_text(geometry)
    vocab = _vocab_count(text)
    if geometry.front_matter:
        if vocab < 1 and not _checkbox(text, geometry):
            return result
    elif geometry.table_index <= BOUNDARY_TABLE_INDEX_MAX:
        # Boundary arm: the region map mislabels this cover, so
        # position plus vocabulary carries the candidacy.
        if vocab < 1:
            return result
    else:
        return result
    role = (
        "continuation"
        if geometry.is_fragment
        else "head"
        if geometry.caption.strip()
        else "standalone"
    )
    group = ClaimGroup(
        family=FAMILY,
        score=0.0,
        state="reach",
        role=role,
        channels={},
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


def apply_cover_seat(
    geometries: list[GeometryText] | tuple[GeometryText, ...],
    results: list[CompetitionResult],
) -> list[CompetitionResult]:
    """Seat cover claims the chain left unclaimed, per geometry."""
    return [
        _seat_one(geometry, result)
        for geometry, result in zip(geometries, results, strict=True)
    ]
