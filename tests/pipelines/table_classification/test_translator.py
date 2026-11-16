"""Tests for the D3 registry-to-planning translator."""

from __future__ import annotations

import pytest

from edgar_sec.engine.tables.extraction.profiles import (
    STRATUM_ANNUAL,
    STRATUM_QUARTERLY,
    ExhibitLink,
    FamilyProfile,
    SupportState,
    registry_state,
)
from edgar_sec.pipelines.table_classification.translator import (
    family_targets,
    planning_triples,
    profile_application_rows,
    registry_state_detail,
    triples_for_family,
)


def _profile(family: str, *types: str) -> FamilyProfile:
    links = tuple(
        ExhibitLink(exhibit_type, (STRATUM_ANNUAL,)) for exhibit_type in types
    )
    return FamilyProfile(
        family,
        "family",
        SupportState(None, None, None, None),
        "seat",
        exhibit_links=links,
    )


def test_registry_yields_one_generic_ex13_triple() -> None:
    triples = planning_triples()
    assert [triple.as_dict() for triple in triples] == [
        {"role": "exhibit", "type": "EX-13", "optional": True}
    ]


def test_linked_and_unlinked_families() -> None:
    assert triples_for_family("balance_sheet") == planning_triples()
    assert triples_for_family("debt_maturity") == ()
    rows = {row.family for row in family_targets()}
    assert "balance_sheet" in rows
    assert "debt_maturity" not in rows
    assert "subsequent_events" not in rows


def test_stratum_filter_excludes_quarterly() -> None:
    assert planning_triples(stratum=STRATUM_ANNUAL) == planning_triples()
    assert planning_triples(stratum=STRATUM_QUARTERLY) == ()


def test_translator_is_generic_over_arbitrary_types() -> None:
    profiles = (_profile("custom_family", "EX-99.1", "ex-13"),)
    triples = planning_triples(profiles=profiles)
    assert [triple.type for triple in triples] == ["EX-99.1", "EX-13"]
    assert all(triple.role == "exhibit" and triple.optional for triple in triples)


def test_unknown_family_is_refused() -> None:
    with pytest.raises(ValueError, match="no registry profile"):
        triples_for_family("not_a_family")


def test_registry_state_digest_is_stable_and_sensitive() -> None:
    first = registry_state_detail()
    assert first == registry_state_detail()
    changed = registry_state_detail(profiles=(_profile("custom_family", "EX-99"),))
    assert changed["digest"] != first["digest"]
    assert first["exhibit_types"] == ["EX-13"]
    opaque = registry_state()
    assert opaque == f"sha256:{first['digest']}"
    assert first["retired_families"] == ["subsequent_events"]


def test_profile_application_rows_match_core_contract() -> None:
    rows = profile_application_rows(("0001-26-1",), families=("balance_sheet",))
    assert rows == (
        {
            "accession": "0001-26-1",
            "family": "balance_sheet",
            "kind": "family",
            "vocabulary_seat": "signature_competition",
        },
    )
