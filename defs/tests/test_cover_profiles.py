"""Contract tests for the shared form-family alias registry and cover profiles."""

from __future__ import annotations

import dataclasses
import importlib

import pytest

sec_forms = importlib.import_module("defs.sec_forms")
cover_mod = importlib.import_module("defs.sec_forms.cover")

form_family = sec_forms.form_family
normalize_form = sec_forms.normalize_form
resolve_alias = sec_forms.resolve_alias
aliases_for_family = sec_forms.aliases_for_family
get_profile = cover_mod.get_profile
COVER_PROFILES = cover_mod.COVER_PROFILES
CoverProfile = cover_mod.CoverProfile
SEC_COVER_PHRASE_RULES = sec_forms.SEC_COVER_PHRASE_RULES


def test_form_family_suffix_stripping() -> None:
    assert form_family("10-K/A") == "10-K"
    assert form_family("10-K_A") == "10-K"
    assert form_family("20-F-POS") == "20-F"
    assert form_family("8-K/A") == "8-K"
    assert form_family("S-1_A") == "S-1"
    assert form_family("6-K") == "6-K"


def test_normalize_form_unknown_returns_none() -> None:
    assert normalize_form(None) is None
    assert normalize_form("") is None
    assert normalize_form("S-1") is None
    assert normalize_form("FORM 3") is None


def test_resolve_alias_known_families() -> None:
    assert resolve_alias("10-K/A") == "10-K"
    assert resolve_alias("10-QSB") == "10-Q"
    assert resolve_alias("8-K12B") == "8-K"
    assert resolve_alias("20-F") == "20-F"
    assert resolve_alias("6-K") == "6-K"


def test_aliases_for_family_contains_canonical() -> None:
    assert "10-K" in aliases_for_family("10-K")
    assert "10-K/A" in aliases_for_family("10-K")
    assert "10-KT" in aliases_for_family("10-K")
    assert "10-QSB" in aliases_for_family("10-Q")
    assert "8-K12G3" in aliases_for_family("8-K")
    assert "20-F" in aliases_for_family("20-F")
    assert "6-K" in aliases_for_family("6-K")


def test_aliases_are_disjoint_by_family() -> None:
    seen: set[str] = set()
    for aliases in sec_forms.FORM_FAMILY_ALIASES.values():
        for alias in aliases:
            assert alias not in seen, f"{alias} duplicated across families"
            seen.add(alias)


def test_profiles_exist_for_registered_families() -> None:
    for family in sec_forms.FORM_FAMILY_ALIASES:
        assert family in COVER_PROFILES


def test_profile_eligibility_matrix() -> None:
    assert get_profile("10-K").eligible is True
    assert get_profile("20-F").eligible is True
    assert get_profile("10-Q").eligible is True
    assert get_profile("8-K").eligible is False
    assert get_profile("6-K").eligible is False
    assert get_profile("GENERIC").eligible is False
    assert get_profile(None).eligible is False
    assert get_profile("S-1").eligible is False


def test_annual_profiles_enable_incorporated_reference() -> None:
    annual = get_profile("10-K")
    quarterly = get_profile("10-Q")
    annual_names = {rule.name for rule in annual.phrase_rules}
    quarterly_names = {rule.name for rule in quarterly.phrase_rules}
    assert "documents_incorporated_reference" in annual_names
    assert "documents_incorporated_reference" not in quarterly_names
    assert "aggregate_market_value" in annual_names
    assert "aggregate_market_value" not in quarterly_names
    assert "auditor_firm_id" in annual_names
    assert "auditor_firm_id" not in quarterly_names


def test_no_cover_profiles_have_no_rules_or_labels() -> None:
    for family in ("8-K", "6-K", "GENERIC"):
        profile = get_profile(family)
        assert profile.phrase_rules == ()
        assert profile.labels == ()
        assert profile.boundary_phrases == ()
        assert profile.evidence_terms == ()


def test_annual_boundary_includes_incorporated_reference() -> None:
    annual = get_profile("10-K")
    quarterly = get_profile("10-Q")
    assert "documents incorporated by reference" in annual.boundary_phrases
    assert "documents incorporated by reference" not in quarterly.boundary_phrases


def test_20_f_profile_extends_annual_common() -> None:
    annual = get_profile("10-K")
    foreign = get_profile("20-F")
    assert foreign.eligible is True
    assert foreign.labels == annual.labels
    assert foreign.boundary_phrases == annual.boundary_phrases
    assert foreign.phrase_rules == annual.phrase_rules


def test_profiles_are_immutable() -> None:
    profile = get_profile("10-K")
    with pytest.raises(dataclasses.FrozenInstanceError):
        profile.family = "10-Q"  # type: ignore[misc]


def test_aggregate_matches_annual_profile_rules() -> None:
    annual = get_profile("10-K")
    assert tuple(SEC_COVER_PHRASE_RULES) == annual.phrase_rules
