"""Priced term vetoes: the priced sets as data (v2 + Step 4 v3).

HARD terms remove a family's claim outright; SCORED terms lower
its score once per claim, however many hit (any-hit). Channels
as priced: lead is caption + prose_before; body is grid text.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from edgar_sec.engine.tables.extraction.core.normalize import normalize_text
from edgar_sec.engine.tables.extraction.vetoes.term_veto_notes import NOTE_VETO_ENTRIES
from edgar_sec.engine.tables.extraction.vetoes.term_veto_statements import (
    STATEMENT_VETO_ENTRIES,
)

if TYPE_CHECKING:
    from edgar_sec.engine.tables.extraction.cascade.geometry_text import GeometryText


@dataclass(frozen=True, slots=True)
class VetoSpec:
    """One family's priced term vetoes for one channel at one tier."""

    family: str
    channel: str
    tier: str
    terms: tuple[str, ...]


# Step 6 v2 sets (record: 2026-11-16-greenfield-step6-v2-
# measurement-record) plus the Step 4 v3 build-act rows (record:
# greenfield-followup-discovery/step4) and the AOCI held-row release.
TERM_VETOES: tuple[VetoSpec, ...] = tuple(
    VetoSpec(*entry) for entry in STATEMENT_VETO_ENTRIES + NOTE_VETO_ENTRIES
)


LEAD_TEXT_CAP = 6000


def lead_channel_text(caption: str, prose_before: str) -> str:
    """The priced lead channel: caption + prose_before, tail-capped."""
    return caption + "\n" + prose_before[-LEAD_TEXT_CAP:]


def term_veto_hits(geometry: GeometryText) -> dict[str, dict[str, str]]:
    """First priced term-veto hit per family and tier.

    Matching is the pricing's own: normalized substring over the
    channel text; lead reads GeometryText.lead, body the grid.
    """
    texts = {
        "lead": normalize_text(geometry.lead),
        "body": normalize_text(geometry.grid_text),
    }
    hits: dict[str, dict[str, str]] = {}
    for spec in TERM_VETOES:
        text = texts[spec.channel]
        if not text:
            continue
        for term in spec.terms:
            if normalize_text(term) in text:
                tiers = hits.setdefault(spec.family, {})
                if spec.tier not in tiers:
                    tiers[spec.tier] = term
                break
    return hits
