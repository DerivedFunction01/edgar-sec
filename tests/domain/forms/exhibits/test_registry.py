"""Tests for pack registry lookup."""

from __future__ import annotations

from edgar_sec.domain.forms.common.exhibits import ExhibitIdentity
from edgar_sec.domain.forms.exhibits.registry import (
    list_active_packs,
    resolve_pack_for_identity,
)


def test_resolve_pack_returns_none():
    """All identity lookups return None in D1."""
    identity = ExhibitIdentity(authority_id="reg_s_k_item_601", code="1")
    assert resolve_pack_for_identity(identity) is None


def test_list_active_packs_empty():
    """No packs are active in D1."""
    assert list_active_packs() == ()
