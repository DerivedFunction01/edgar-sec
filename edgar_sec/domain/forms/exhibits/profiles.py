"""Exhibit authority profiles for Item 601 and Form 20-F."""

from __future__ import annotations

from edgar_sec.domain.forms.common.exhibits import ExhibitAuthorityProfile

ITEM_601_AUTHORITY_PROFILE = ExhibitAuthorityProfile(
    authority_id="reg_s_k_item_601",
    version="v1",
    applicable_forms=("10-K", "10-Q", "8-K"),
    candidate_tiers=("tier1", "tier2"),
    veto_signals=("conflict", "invalid"),
)

_F20F_AUTHORITY_PROFILE = ExhibitAuthorityProfile(
    authority_id="form_20f",
    version="v1",
    applicable_forms=("20-F",),
    candidate_tiers=("tier1", "tier2"),
    veto_signals=("conflict", "invalid"),
)

_PROFILES: dict[str, ExhibitAuthorityProfile] = {
    ITEM_601_AUTHORITY_PROFILE.authority_id: ITEM_601_AUTHORITY_PROFILE,
    _F20F_AUTHORITY_PROFILE.authority_id: _F20F_AUTHORITY_PROFILE,
}


def get_exhibit_authority_profile(authority_id: str) -> ExhibitAuthorityProfile | None:
    """Get an exhibit authority profile by authority ID."""
    return _PROFILES.get(authority_id, None)


def get_authorities_for_form(form: str) -> tuple[ExhibitAuthorityProfile, ...]:
    """Get all exhibit authority profiles applicable to a form."""
    return tuple(p for p in _PROFILES.values() if form in p.applicable_forms)


__all__ = [
    "ITEM_601_AUTHORITY_PROFILE",
    "get_exhibit_authority_profile",
    "get_authorities_for_form",
]
