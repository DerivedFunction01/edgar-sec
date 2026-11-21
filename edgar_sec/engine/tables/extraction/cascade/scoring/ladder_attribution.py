"""Ladder attribution: the priced debt/lease edge terms decide
a contested pair, and contest or flip a lone ladder claim.
"""

from __future__ import annotations

import math

from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_scoring import (
    FamilyScore,
)
from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_text import (
    GeometryText,
)
from edgar_sec.engine.tables.extraction.core.text.normalize import normalize_text
from edgar_sec.engine.tables.extraction.core.subjects.signature_profiles import (
    LadderTerm,
)


def ladder_direction(
    geometry: GeometryText,
    ladder_terms: tuple[LadderTerm, ...],
) -> float:
    """Signed debt/lease evidence: positive leans lease, from the edge."""
    text = geometry.stub_text + " " + normalize_text(geometry.caption)
    direction = 0.0
    for spec in ladder_terms:
        if spec.term in text:
            direction += math.log(
                (spec.support_lease + 1.0) / (spec.support_debt + 1.0)
            )
    return direction


def apply_ladder_attribution(
    claims: list[str],
    contested: list[str],
    scores: dict[str, FamilyScore],
    geometry: GeometryText,
    ladder_terms: tuple[LadderTerm, ...],
    *,
    margin: float,
    single_mode: str,
) -> tuple[list[str], list[str]]:
    """Attribute the ladder families by the priced edge terms.

    Returns the (possibly rebound) contested list and the
    families the ladder attributed away.
    """
    # Cure 2 (ladder attribution): the map's priced edge terms
    # decide debt vs lease before the pair stays contested.
    attributed: list[str] = []
    if "debt_maturity" in claims and "lease_maturity" in claims:
        direction = ladder_direction(geometry, ladder_terms)
        loser = None
        if direction >= margin:
            loser = "debt_maturity"
        elif direction <= -margin:
            loser = "lease_maturity"
        if loser is not None:
            claims.remove(loser)
            attributed.append(loser)
            if loser in contested:
                contested.remove(loser)
            if len(contested) < 2:
                contested = []
    # Cure 2, single-claim arm: a decisive edge direction against
    # a lone ladder claim contests or flips it (priced arms).
    if single_mode != "off":
        ladder_claims = [f for f in claims if f in ("debt_maturity", "lease_maturity")]
        if len(ladder_claims) == 1:
            holder = ladder_claims[0]
            other = "lease_maturity" if holder == "debt_maturity" else "debt_maturity"
            direction = ladder_direction(geometry, ladder_terms)
            opposed = (
                direction >= margin
                if holder == "debt_maturity"
                else direction <= -margin
            )
            if opposed and other in scores:
                if single_mode == "flip":
                    claims.remove(holder)
                    claims.append(other)
                    attributed.append(holder)
                elif not contested:
                    claims.append(other)
                    contested = [holder, other]
    return contested, attributed
