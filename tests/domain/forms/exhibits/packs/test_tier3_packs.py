"""Tests for Tier 3 exhibit pack definitions."""

from edgar_sec.domain.forms.exhibits.packs import (
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


def test_tier3_pack_id_uniqueness():
    """Verify each Tier 3 pack has a unique pack_id."""
    packs = [
        ex9.PACK,
        ex13.PACK,
        ex20.PACK,
        ex31_ii.PACK,
        ex33.PACK,
        ex34.PACK,
        ex35.PACK,
        ex36.PACK,
        ex95.PACK,
        ex96.PACK,
        ex98.PACK,
        ex106.PACK,
    ]
    pack_ids = [p.pack_id for p in packs]
    assert len(pack_ids) == len(set(pack_ids))


def test_tier3_no_hardcoded_form_10k():
    """Verify no Tier 3 packs hardcode 'Form 10-K'."""
    packs = [
        ex9.PACK,
        ex13.PACK,
        ex20.PACK,
        ex31_ii.PACK,
        ex33.PACK,
        ex34.PACK,
        ex35.PACK,
        ex36.PACK,
        ex95.PACK,
        ex96.PACK,
        ex98.PACK,
        ex106.PACK,
    ]
    for pack in packs:
        for anchor in pack.title_anchors + pack.primary_anchors:
            assert "form 10-k" not in anchor.lower()
        for token in pack.secondary_tokens:
            assert "form 10-k" not in token.lower()


def test_tier3_tier_assignment():
    """Verify all Tier 3 packs have tier='tier3'."""
    packs = [
        ex9.PACK,
        ex13.PACK,
        ex20.PACK,
        ex31_ii.PACK,
        ex33.PACK,
        ex34.PACK,
        ex35.PACK,
        ex36.PACK,
        ex95.PACK,
        ex96.PACK,
        ex98.PACK,
        ex106.PACK,
    ]
    for pack in packs:
        assert pack.tier == "tier3"


def test_tier3_authority_id():
    """Verify all Tier 3 packs use correct authority ID."""
    packs = [
        ex9.PACK,
        ex13.PACK,
        ex20.PACK,
        ex31_ii.PACK,
        ex33.PACK,
        ex34.PACK,
        ex35.PACK,
        ex36.PACK,
        ex95.PACK,
        ex96.PACK,
        ex98.PACK,
        ex106.PACK,
    ]
    for pack in packs:
        assert pack.authority_id == "reg_s_k_item_601"
