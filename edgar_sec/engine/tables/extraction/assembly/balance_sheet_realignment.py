"""Balance-sheet realignment of assembled assignments.

Assembly's arbitration seats balance_sheet claims the filing
competition's primary gate never admits, and misses claims
the gate does admit; this pass re-reads the gate's verdict.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from edgar_sec.engine.tables.extraction.cascade.filing_competition import (
    compete_filing,
    compete_filing_gated,
)
from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_text import (
    geometry_text_from_table,
)
from edgar_sec.engine.tables.extraction.core.registry import RESIDUAL_FAMILY

if TYPE_CHECKING:
    from edgar_sec.engine.tables.extraction.assembly.assembly import (
        GeometryAssignment,
        _Member,
    )
    from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_scoring import (
        CompetitionResult,
    )
    from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_text import (
        GeometryText,
    )

_BALANCE_SHEET = "balance_sheet"


def realign_balance_sheet(
    members: list[_Member],
    by_position: dict[int, GeometryAssignment],
) -> None:
    """Realign balance_sheet assignments to the competition's
    discipline: an assignment stands only where the gate admits
    it; a promotion needs final-claim survival as well."""
    texts = [geometry_text_from_table(member.table) for member in members]
    gated = compete_filing_gated(texts)
    if not any(result.claims for result in gated):
        return
    survived = _final_survivors(texts, gated, by_position)
    for position, result in enumerate(gated):
        current = by_position[position]
        admitted = _BALANCE_SHEET in result.claims
        if current.family == _BALANCE_SHEET and not admitted:
            by_position[position] = replace(
                current, family=RESIDUAL_FAMILY, mechanism="residual"
            )
        elif position in survived:
            by_position[position] = replace(
                current, family=_BALANCE_SHEET, mechanism="winner"
            )


def _final_survivors(
    texts: list[GeometryText],
    gated: list[CompetitionResult],
    by_position: dict[int, GeometryAssignment],
) -> set[int]:
    """Positions the promotion may seat: gate-admitted claims
    on non-balance-sheet assignments that the full competition
    still seats in its final claims."""
    candidates = [
        position
        for position, result in enumerate(gated)
        if by_position[position].family != _BALANCE_SHEET
        and _BALANCE_SHEET in result.claims
    ]
    if not candidates:
        return set()
    finals = compete_filing(texts)
    return {
        position for position in candidates if _BALANCE_SHEET in finals[position].claims
    }
