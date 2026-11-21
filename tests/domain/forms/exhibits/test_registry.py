"""Tests for pack registry lookup."""

from __future__ import annotations

from edgar_sec.domain.forms.common.exhibits import ExhibitIdentity
from edgar_sec.domain.forms.exhibits.coverage import get_coverage_entry
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


def test_resolve_pack_falls_back_to_base_code_for_sub_codes():
    """A sub-code with no pack of its own resolves its base code's pack."""
    for code in ("99.1", "99.2"):
        pack = resolve_pack_for_identity(
            ExhibitIdentity(authority_id="reg_s_k_item_601", code=code)
        )
        assert pack is not None
        assert pack.pack_id == "ex99"


def test_resolve_pack_sub_code_without_base_pack_stays_none():
    """A sub-code whose base code has no pack does not resolve."""
    for code in ("31.3", "3.3"):
        assert (
            resolve_pack_for_identity(
                ExhibitIdentity(authority_id="reg_s_k_item_601", code=code)
            )
            is None
        )


def test_disabled_and_unsupported_mappings_do_not_resolve():
    """Disabled authorities and unsupported codes fail closed."""
    assert (
        resolve_pack_for_identity(ExhibitIdentity(authority_id="form_20f", code="4"))
        is None
    )
    assert (
        resolve_pack_for_identity(
            ExhibitIdentity(authority_id="reg_s_k_item_601", code="106")
        )
        is None
    )


def test_list_active_packs_return_format():
    """list_active_packs returns (authority_id, code) tuples."""
    active = list_active_packs()
    assert len(active) == 35

    for authority_id, code in active:
        pack = resolve_pack_for_identity(
            ExhibitIdentity(authority_id=authority_id, code=code)
        )
        entry = get_coverage_entry(authority_id, code)
        assert pack is not None
        assert pack.authority_id == authority_id
        assert entry is not None
        assert entry.coverage_status in {"candidate", "partial"}

    # Verify Item 601 entry
    assert ("reg_s_k_item_601", "3.1") in active

    assert ("form_20f", "4") not in active
