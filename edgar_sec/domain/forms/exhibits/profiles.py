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

# Regulation AB asset-data exhibits are companion-parsed, not anchor
# evaluated, so the profile carries no candidate tiers.
ABS_EE_AUTHORITY_PROFILE = ExhibitAuthorityProfile(
    authority_id="reg_ab",
    version="v1",
    applicable_forms=("ABS-EE", "10-D"),
    candidate_tiers=(),
    veto_signals=(),
)

_PROFILES: dict[str, ExhibitAuthorityProfile] = {
    ITEM_601_AUTHORITY_PROFILE.authority_id: ITEM_601_AUTHORITY_PROFILE,
    _F20F_AUTHORITY_PROFILE.authority_id: _F20F_AUTHORITY_PROFILE,
    ABS_EE_AUTHORITY_PROFILE.authority_id: ABS_EE_AUTHORITY_PROFILE,
}


def get_exhibit_authority_profile(authority_id: str) -> ExhibitAuthorityProfile | None:
    """Get an exhibit authority profile by authority ID."""
    return _PROFILES.get(authority_id, None)


def get_authorities_for_form(form: str) -> tuple[ExhibitAuthorityProfile, ...]:
    """Get all exhibit authority profiles applicable to a form."""
    return tuple(p for p in _PROFILES.values() if form in p.applicable_forms)


__all__ = [
    "ABS_EE_AUTHORITY_PROFILE",
    "ITEM_601_AUTHORITY_PROFILE",
    "get_exhibit_authority_profile",
    "get_authorities_for_form",
]
