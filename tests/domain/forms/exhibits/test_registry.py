"""Tests for pack registry lookup."""

from __future__ import annotations

from edgar_sec.domain.forms.common.exhibits import ExhibitIdentity
from edgar_sec.domain.forms.exhibits.registry import (
    list_active_packs,
    resolve_pack_for_identity,
)


def test_resolve_pack_returns_pack():
    """Pack lookups return active packs when found."""
    identity = ExhibitIdentity(authority_id="reg_s_k_item_601", code="3.1")
    pack = resolve_pack_for_identity(identity)
    assert pack is not None
    assert pack.pack_id == "ex3_1"


def test_resolve_pack_returns_none_missing():
    """Lookups return None when code is not registered."""
    identity = ExhibitIdentity(authority_id="reg_s_k_item_601", code="999")
    assert resolve_pack_for_identity(identity) is None


def test_list_active_packs_nonempty():
    """Tier 1, 2, and 3 packs are active."""
    active = list_active_packs()
    assert len(active) == 36  # 9 (Tier1) + 15 (Tier2) + 12 (Tier3)
    # Tier 1
    assert "3.1" in active
    assert "3.2" in active
    assert "4" in active
    assert "10" in active
    assert "21" in active
    assert "23" in active
    assert "24" in active
    assert "31.1" in active
    assert "32.1" in active
    # Tier 2
    assert "1" in active
    assert "2" in active
    assert "5" in active
    assert "14" in active
    assert "97" in active
    assert "99" in active
    assert "107" in active
    # Tier 3
    assert "9" in active
    assert "13" in active
    assert "31.2" in active
    assert "95" in active
    assert "96" in active
    assert "106" in active
