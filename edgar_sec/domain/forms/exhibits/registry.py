"""Authority + code to pack lookup seam."""

from __future__ import annotations

from edgar_sec.domain.forms.common.exhibits import ExhibitIdentity
from edgar_sec.domain.forms.exhibits.packs import (
    ex3_1,
    ex3_2,
    ex4,
    ex10,
    ex21,
    ex23,
    ex24,
    ex31_i,
    ex32,
    ex1,
    ex2,
    ex5,
    ex8,
    ex14,
    ex15,
    ex16,
    ex17,
    ex18,
    ex19,
    ex22,
    ex25,
    ex97,
    ex99,
    ex107,
    ex9,
    ex13,
    ex20,
    ex31_ii,
    ex33,
    ex34,
    ex35,
    ex36,
    ex95,
    ex96,
    ex98,
    ex106,
)

_PACK_BY_CODE: dict[str, object] = {
    "3.1": ex3_1.PACK,
    "3.2": ex3_2.PACK,
    "4": ex4.PACK,
    "10": ex10.PACK,
    "21": ex21.PACK,
    "23": ex23.PACK,
    "24": ex24.PACK,
    "31.1": ex31_i.PACK,
    "32.1": ex32.PACK,
    "1": ex1.PACK,
    "2": ex2.PACK,
    "5": ex5.PACK,
    "8": ex8.PACK,
    "14": ex14.PACK,
    "15": ex15.PACK,
    "16": ex16.PACK,
    "17": ex17.PACK,
    "18": ex18.PACK,
    "19": ex19.PACK,
    "22": ex22.PACK,
    "25": ex25.PACK,
    "97": ex97.PACK,
    "99": ex99.PACK,
    "107": ex107.PACK,
    "9": ex9.PACK,
    "13": ex13.PACK,
    "20": ex20.PACK,
    "31.2": ex31_ii.PACK,
    "33": ex33.PACK,
    "34": ex34.PACK,
    "35": ex35.PACK,
    "36": ex36.PACK,
    "95": ex95.PACK,
    "96": ex96.PACK,
    "98": ex98.PACK,
    "106": ex106.PACK,
}
"""Authority-qualified code -> pack lookup."""


def resolve_pack_for_identity(identity: ExhibitIdentity) -> object | None:
    """Resolve content pack for an exhibit identity.

    Returns the pack object if found, otherwise None.
    """
    return _PACK_BY_CODE.get(identity.code)


def list_active_packs() -> tuple[str, ...]:
    """List active pack IDs."""
    return tuple(_PACK_BY_CODE.keys())


__all__ = [
    "resolve_pack_for_identity",
    "list_active_packs",
]
