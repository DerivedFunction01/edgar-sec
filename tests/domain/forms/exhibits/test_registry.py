"""Tests for pack registry lookup."""

from __future__ import annotations

from edgar_sec.domain.forms.common.exhibits import ExhibitIdentity
from edgar_sec.domain.forms.exhibits.registry import (
    list_active_packs,
    resolve_pack_for_identity,
)


def test_resolve_pack_by_authority():
    """Pack lookup requires both authority_id and code."""
    identity = ExhibitIdentity(authority_id="reg_s_k_item_601", code="3.1")
    pack = resolve_pack_for_identity(identity)
    assert pack is not None
    assert pack.pack_id == "ex3_1"


def test_resolve_pack_returns_none_missing_authority():
    """Lookup returns None when authority/code pair is not registered."""
    identity = ExhibitIdentity(authority_id="form_20f", code="999")
    assert resolve_pack_for_identity(identity) is None


def test_form_20f_mappings():
    """Form 20-F codes resolve to mapped packs."""
    identity = ExhibitIdentity(authority_id="form_20f", code="4")
    pack = resolve_pack_for_identity(identity)
    assert pack is not None
    assert pack.pack_id == "ex10"  # Form 20-F Item 4 → Material Contracts


def test_list_active_packs_return_format():
    """list_active_packs returns (authority_id, code) tuples."""
    active = list_active_packs()
    assert len(active) == 47  # 35 (Item 601) + 12 (Form 20-F)

    # Verify Item 601 entry
    assert ("reg_s_k_item_601", "3.1") in active

    # Verify Form 20-F entry
    assert ("form_20f", "4") in active
