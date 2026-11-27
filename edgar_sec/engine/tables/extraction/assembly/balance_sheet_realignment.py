"""Balance-sheet realignment of assembled assignments.

Assembly's arbitration seats balance_sheet claims the filing
competition's primary gate never admits, and misses claims
the gate does admit; this pass re-reads the gate's verdict.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from edgar_sec.engine.tables.extraction.cascade.filing_competition import (
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

_BALANCE_SHEET = "balance_sheet"


def realign_balance_sheet(
    members: list[_Member],
    by_position: dict[int, GeometryAssignment],
) -> None:
    """Realign balance_sheet assignments to the gate's
    discipline: an assignment stands only where the primary
    gate admits the claim; admitted claims seat the family."""
    texts = [geometry_text_from_table(member.table) for member in members]
    gated = compete_filing_gated(texts)
    if not any(result.claims for result in gated):
        return
    for position, result in enumerate(gated):
        current = by_position[position]
        admitted = _BALANCE_SHEET in result.claims
        if current.family == _BALANCE_SHEET and not admitted:
            by_position[position] = replace(
                current, family=RESIDUAL_FAMILY, mechanism="residual"
            )
        elif current.family != _BALANCE_SHEET and admitted:
            by_position[position] = replace(
                current, family=_BALANCE_SHEET, mechanism="winner"
            )
