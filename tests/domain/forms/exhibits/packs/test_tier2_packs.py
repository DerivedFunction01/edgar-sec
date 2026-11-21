"""Tests for Tier 2 exhibit pack definitions."""

from edgar_sec.domain.forms.exhibits.packs import (
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
)


def test_tier2_pack_id_uniqueness():
    """Verify each Tier 2 pack has a unique pack_id."""
    packs = [
        ex1.PACK,
        ex2.PACK,
        ex5.PACK,
        ex8.PACK,
        ex14.PACK,
        ex15.PACK,
        ex16.PACK,
        ex17.PACK,
        ex18.PACK,
        ex19.PACK,
        ex22.PACK,
        ex25.PACK,
        ex97.PACK,
        ex99.PACK,
        ex107.PACK,
    ]
    pack_ids = [p.pack_id for p in packs]
    assert len(pack_ids) == len(set(pack_ids))


def test_tier2_no_hardcoded_form_10k():
    """Verify no Tier 2 packs hardcode 'Form 10-K'."""
    packs = [
        ex1.PACK,
        ex2.PACK,
        ex5.PACK,
        ex8.PACK,
        ex14.PACK,
        ex15.PACK,
        ex16.PACK,
        ex17.PACK,
        ex18.PACK,
        ex19.PACK,
        ex22.PACK,
        ex25.PACK,
        ex97.PACK,
        ex99.PACK,
        ex107.PACK,
    ]
    for pack in packs:
        for anchor in pack.title_anchors + pack.primary_anchors:
            assert "form 10-k" not in anchor.lower()
        for token in pack.secondary_tokens:
            assert "form 10-k" not in token.lower()


def test_tier2_tier_assignment():
    """Verify all Tier 2 packs have tier='tier2'."""
    packs = [
        ex1.PACK,
        ex2.PACK,
        ex5.PACK,
        ex8.PACK,
        ex14.PACK,
        ex15.PACK,
        ex16.PACK,
        ex17.PACK,
        ex18.PACK,
        ex19.PACK,
        ex22.PACK,
        ex25.PACK,
        ex97.PACK,
        ex99.PACK,
        ex107.PACK,
    ]
    for pack in packs:
        assert pack.tier == "tier2"


def test_tier2_authority_id():
    """Verify all Tier 2 packs use correct authority ID."""
    packs = [
        ex1.PACK,
        ex2.PACK,
        ex5.PACK,
        ex8.PACK,
        ex14.PACK,
        ex15.PACK,
        ex16.PACK,
        ex17.PACK,
        ex18.PACK,
        ex19.PACK,
        ex22.PACK,
        ex25.PACK,
        ex97.PACK,
        ex99.PACK,
        ex107.PACK,
    ]
    for pack in packs:
        assert pack.authority_id == "reg_s_k_item_601"
