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
        _Group,
        _Member,
    )

_BALANCE_SHEET = "balance_sheet"


def realign_balance_sheet(
    members: list[_Member],
    groups: list[_Group],
    sectioned: dict[int, str],
    by_position: dict[int, GeometryAssignment],
) -> None:
    """Realign balance_sheet assignments to the gate's
    discipline, at statement level: a statement follows the
    gate's read on its head; joins follow their statement."""
    texts = [geometry_text_from_table(member.table) for member in members]
    gated = compete_filing_gated(texts)
    admitted = {
        position
        for position, result in enumerate(gated)
        if _BALANCE_SHEET in result.claims
    }

    def seat(position: int, family: str) -> None:
        current = by_position[position]
        if family == RESIDUAL_FAMILY:
            by_position[position] = replace(
                current, family=RESIDUAL_FAMILY, mechanism="residual"
            )
        elif current.family != family:
            by_position[position] = replace(
                current,
                family=family,
                mechanism="winner" if current.mechanism != "join" else "join",
            )

    grouped = set()
    for group in groups:
        head = next(
            (m for m in group.members if m.family == group.family),
            group.members[0],
        )
        grouped.update(m.position for m in group.members)
        if group.family == _BALANCE_SHEET and head.position not in admitted:
            for member in group.members:
                seat(member.position, RESIDUAL_FAMILY)
        elif group.family != _BALANCE_SHEET and head.position in admitted:
            for member in group.members:
                seat(member.position, _BALANCE_SHEET)
    for member in members:
        if member.position in grouped or member.position in sectioned:
            continue
        if member.position in admitted:
            seat(member.position, _BALANCE_SHEET)
    for position, family in sectioned.items():
        if family == _BALANCE_SHEET and position not in admitted:
            seat(position, RESIDUAL_FAMILY)
        elif family != _BALANCE_SHEET and position in admitted:
            seat(position, _BALANCE_SHEET)
