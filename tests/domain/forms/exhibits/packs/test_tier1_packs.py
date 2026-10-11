"""Tests for Tier 1 exhibit pack definitions."""

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
)


def test_pack_id_uniqueness():
    """Verify each pack has a unique pack_id."""
    packs = [
        ex3_1.PACK,
        ex3_2.PACK,
        ex4.PACK,
        ex10.PACK,
        ex21.PACK,
        ex23.PACK,
        ex24.PACK,
        ex31_i.PACK,
        ex32.PACK,
    ]
    pack_ids = [p.pack_id for p in packs]
    assert len(pack_ids) == len(set(pack_ids))


def test_no_hardcoded_form_10k():
    """Verify no Tier 1 packs hardcode 'Form 10-K'."""
    packs = [
        ex3_1.PACK,
        ex3_2.PACK,
        ex4.PACK,
        ex10.PACK,
        ex21.PACK,
        ex23.PACK,
        ex24.PACK,
        ex31_i.PACK,
        ex32.PACK,
    ]
    for pack in packs:
        for anchor in pack.title_anchors + pack.primary_anchors:
            assert "form 10-k" not in anchor.lower()
        for token in pack.secondary_tokens:
            assert "form 10-k" not in token.lower()


def test_pack_tier_assignment():
    """Verify all Tier 1 packs have tier='tier1'."""
    packs = [
        ex3_1.PACK,
        ex3_2.PACK,
        ex4.PACK,
        ex10.PACK,
        ex21.PACK,
        ex23.PACK,
        ex24.PACK,
        ex31_i.PACK,
        ex32.PACK,
    ]
    for pack in packs:
        assert pack.tier == "tier1"


def test_pack_authority_id():
    """Verify all packs use correct authority ID."""
    packs = [
        ex3_1.PACK,
        ex3_2.PACK,
        ex4.PACK,
        ex10.PACK,
        ex21.PACK,
        ex23.PACK,
        ex24.PACK,
        ex31_i.PACK,
        ex32.PACK,
    ]
    for pack in packs:
        assert pack.authority_id == "reg_s_k_item_601"


def test_subpack_parent_code():
    """Verify sub-packs have correct parent_code."""
    assert ex3_1.PACK.parent_code == "3"
    assert ex3_2.PACK.parent_code == "3"
    assert ex31_i.PACK.parent_code == "31"
    assert ex32.PACK.parent_code == "32"
