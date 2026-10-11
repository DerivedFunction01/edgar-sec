"""Authority + code to pack lookup seam."""

from __future__ import annotations

from edgar_sec.domain.forms.common.exhibits import ExhibitIdentity
from edgar_sec.domain.forms.exhibits.packs import (
    ex1,
    ex2,
    ex3_1,
    ex3_2,
    ex4,
    ex5,
    ex8,
    ex9,
    ex10,
    ex13,
    ex14,
    ex15,
    ex16,
    ex17,
    ex18,
    ex19,
    ex20,
    ex21,
    ex22,
    ex23,
    ex24,
    ex25,
    ex31_i,
    ex31_ii,
    ex32,
    ex33,
    ex34,
    ex35,
    ex36,
    ex95,
    ex96,
    ex97,
    ex98,
    ex99,
    ex106,
    ex107,
)

_PACK_BY_CODE: dict[tuple[str, str], object] = {
    # Tier 1: Item 601 (reg_s_k_item_601)
    ("reg_s_k_item_601", "3.1"): ex3_1.PACK,
    ("reg_s_k_item_601", "3.2"): ex3_2.PACK,
    ("reg_s_k_item_601", "4"): ex4.PACK,
    ("reg_s_k_item_601", "10"): ex10.PACK,
    ("reg_s_k_item_601", "21"): ex21.PACK,
    ("reg_s_k_item_601", "23"): ex23.PACK,
    ("reg_s_k_item_601", "24"): ex24.PACK,
    ("reg_s_k_item_601", "31.1"): ex31_i.PACK,
    ("reg_s_k_item_601", "32.1"): ex32.PACK,
    # Tier 2: Item 601 (reg_s_k_item_601)
    ("reg_s_k_item_601", "1"): ex1.PACK,
    ("reg_s_k_item_601", "2"): ex2.PACK,
    ("reg_s_k_item_601", "5"): ex5.PACK,
    ("reg_s_k_item_601", "8"): ex8.PACK,
    ("reg_s_k_item_601", "14"): ex14.PACK,
    ("reg_s_k_item_601", "15"): ex15.PACK,
    ("reg_s_k_item_601", "16"): ex16.PACK,
    ("reg_s_k_item_601", "17"): ex17.PACK,
    ("reg_s_k_item_601", "18"): ex18.PACK,
    ("reg_s_k_item_601", "19"): ex19.PACK,
    ("reg_s_k_item_601", "22"): ex22.PACK,
    ("reg_s_k_item_601", "25"): ex25.PACK,
    ("reg_s_k_item_601", "97"): ex97.PACK,
    ("reg_s_k_item_601", "99"): ex99.PACK,
    ("reg_s_k_item_601", "107"): ex107.PACK,
    # Tier 3: Item 601 (reg_s_k_item_601)
    ("reg_s_k_item_601", "9"): ex9.PACK,
    ("reg_s_k_item_601", "13"): ex13.PACK,
    ("reg_s_k_item_601", "20"): ex20.PACK,
    ("reg_s_k_item_601", "31.2"): ex31_ii.PACK,
    ("reg_s_k_item_601", "33"): ex33.PACK,
    ("reg_s_k_item_601", "34"): ex34.PACK,
    ("reg_s_k_item_601", "35"): ex35.PACK,
    ("reg_s_k_item_601", "36"): ex36.PACK,
    ("reg_s_k_item_601", "95"): ex95.PACK,
    ("reg_s_k_item_601", "96"): ex96.PACK,
    ("reg_s_k_item_601", "98"): ex98.PACK,
    ("reg_s_k_item_601", "106"): ex106.PACK,
    # Form 20-F mappings (form_20f)
    ("form_20f", "1"): ex3_1.PACK,
    ("form_20f", "2"): ex4.PACK,
    ("form_20f", "3"): ex9.PACK,
    ("form_20f", "4"): ex10.PACK,
    ("form_20f", "8"): ex21.PACK,
    ("form_20f", "11"): ex14.PACK,
    ("form_20f", "12"): ex31_i.PACK,
    ("form_20f", "13"): ex32.PACK,
    ("form_20f", "14"): ex5.PACK,
    ("form_20f", "16"): ex95.PACK,
    ("form_20f", "17"): ex22.PACK,
}
"""Authority-qualified (authority_id, code) -> pack lookup."""


def resolve_pack_for_identity(identity: ExhibitIdentity) -> object | None:
    """Resolve content pack for an exhibit identity.

    Returns the pack object if found, otherwise None.
    """
    return _PACK_BY_CODE.get((identity.authority_id, identity.code))


def list_active_packs() -> tuple[tuple[str, str], ...]:
    """List active pack IDs as (authority_id, code) tuples."""
    return tuple(_PACK_BY_CODE.keys())


__all__ = [
    "resolve_pack_for_identity",
    "list_active_packs",
]
