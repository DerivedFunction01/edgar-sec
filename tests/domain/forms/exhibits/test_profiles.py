"""Tests for exhibit authority profiles."""

from __future__ import annotations

from edgar_sec.domain.forms.exhibits.profiles import (
    ITEM_601_AUTHORITY_PROFILE,
    get_authorities_for_form,
    get_exhibit_authority_profile,
)


def test_item_601_profile():
    """Item 601 authority profile is registered."""
    assert ITEM_601_AUTHORITY_PROFILE is not None
    assert ITEM_601_AUTHORITY_PROFILE.authority_id == "reg_s_k_item_601"
    assert ITEM_601_AUTHORITY_PROFILE.applicable_forms == ("10-K", "10-Q", "8-K")


def test_get_authority_by_id():
    """Authority profile lookup by ID works."""
    assert (
        get_exhibit_authority_profile("reg_s_k_item_601") is ITEM_601_AUTHORITY_PROFILE
    )
    assert get_exhibit_authority_profile("nonexistent") is None


def test_get_authorities_for_form():
    """Authority profile lookup by form works."""
    auths = get_authorities_for_form("10-K")
    assert ITEM_601_AUTHORITY_PROFILE in auths
    assert len(auths) == 1
    auths = get_authorities_for_form("20-F")
    # 20-F authority profile exists but is disabled in D1
    assert len(auths) == 1
    assert auths[0].authority_id == "form_20f"
