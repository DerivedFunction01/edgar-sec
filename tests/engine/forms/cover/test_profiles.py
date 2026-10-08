"""Contract tests for the composed form-family cover profiles."""

from __future__ import annotations

import dataclasses

import pytest

from edgar_sec.domain.forms.common.aliases import FORM_FAMILY_ALIASES
from edgar_sec.domain.forms.common.forward_looking import FORWARD_LOOKING_PHRASES
from edgar_sec.domain.forms.common.rules import COMMON_PHRASE_RULES
from edgar_sec.domain.forms.common.vocabulary import (
    COVER_EVIDENCE_TERMS,
    COVER_LABELS_FLAT,
    COVER_START_IDENTITY_TERMS,
)
from edgar_sec.domain.forms.families.annual.checkmarks import ANNUAL_CHECKBOX_SCHEMA
from edgar_sec.domain.forms.families.annual.evidence import (
    ANNUAL_ADDITIONAL_PHRASE_RULES,
    AnnualReportEvidence,
)
from edgar_sec.domain.forms.families.annual.taxonomy import (
    FORM_10K_DERIVED,
    FORM_20F_DERIVED,
)
from edgar_sec.domain.forms.families.current.taxonomy import FORM_8K_ITEMS
from edgar_sec.domain.forms.families.quarterly.checkmarks import (
    QUARTERLY_CHECKBOX_SCHEMA,
)
from edgar_sec.domain.forms.families.quarterly.taxonomy import FORM_10Q_DERIVED
from edgar_sec.engine.forms.cover.models import BoundarySignal
from edgar_sec.engine.forms.cover.profiles import (
    ANNUAL_COVER_LABELS,
    COMMON_COVER_LABELS,
    COVER_PROFILES,
    NO_COVER_LABELS,
    NO_COVER_PHRASE_RULES,
    QUARTERLY_COVER_LABELS,
    QUARTERLY_PHRASE_RULES,
    CoverProfile,
    build_annual_profile,
    build_current_profile,
    build_no_cover_profile,
    build_quarterly_profile,
    get_profile,
)
from edgar_sec.engine.forms.cover.rules import compile_cover_rules
from edgar_sec.foundation.text.evidence import LexicalEvidencePack

COVER_FAMILIES = ("10-K", "20-F", "10-Q")
GENERIC_FAMILIES = ("8-K", "6-K", "GENERIC")
NO_COVER_FAMILIES = ("8-K", "6-K", "GENERIC")
LEXICAL_FAMILIES = ("10-K", "20-F", "10-Q", "8-K", "6-K")


def test_profiles_exist_for_registered_families() -> None:
    for family in FORM_FAMILY_ALIASES:
        assert family in COVER_PROFILES
    assert "GENERIC" in COVER_PROFILES


def test_profile_boundary_capability_matrix() -> None:
    assert get_profile("10-K").boundary is not None
    assert get_profile("20-F").boundary is not None
    assert get_profile("10-Q").boundary is not None
    assert get_profile("8-K").boundary is not None
    assert get_profile("6-K").boundary is not None
    assert get_profile("GENERIC").boundary is not None
    assert get_profile(None).boundary is not None
    assert get_profile("S-1").boundary is not None


def test_annual_profiles_enable_incorporated_reference() -> None:
    annual_names = {rule.name for rule in get_profile("10-K").healing_rules}
    quarterly_names = {rule.name for rule in get_profile("10-Q").healing_rules}
    for annual_only in (
        "documents_incorporated_reference",
        "aggregate_market_value",
        "auditor_firm_id",
    ):
        assert annual_only in annual_names
        assert annual_only not in quarterly_names


def test_generic_cover_profiles_have_common_rules_and_labels() -> None:
    for family in GENERIC_FAMILIES:
        profile = get_profile(family)
        assert profile.healing_rules == tuple(COMMON_PHRASE_RULES)
        assert profile.labels == COMMON_COVER_LABELS
        assert profile.boundary is not None
        assert profile.evidence_terms == COMMON_COVER_LABELS


def test_annual_boundary_enables_incorporated_reference() -> None:
    annual = get_profile("10-K")
    quarterly = get_profile("10-Q")
    assert annual.boundary is not None
    assert quarterly.boundary is not None
    assert BoundarySignal.INCORPORATED_REFERENCE in annual.boundary.signals
    assert BoundarySignal.INCORPORATED_REFERENCE not in quarterly.boundary.signals


def test_20_f_profile_extends_annual_common() -> None:
    annual = get_profile("10-K")
    foreign = get_profile("20-F")
    assert foreign.boundary == annual.boundary
    assert foreign.labels == annual.labels
    assert foreign.healing_rules == annual.healing_rules
    assert foreign.cover_evidence == annual.cover_evidence
    assert foreign.body_evidence == annual.body_evidence
    assert foreign.checkbox_schema == annual.checkbox_schema
    assert foreign.derived_taxonomy == FORM_20F_DERIVED
    assert annual.derived_taxonomy == FORM_10K_DERIVED


def test_profiles_are_immutable() -> None:
    profile = get_profile("10-K")
    with pytest.raises(dataclasses.FrozenInstanceError):
        profile.family = "10-Q"  # type: ignore[misc]


def test_aggregate_matches_annual_profile_rules() -> None:
    expected = tuple(COMMON_PHRASE_RULES) + tuple(ANNUAL_ADDITIONAL_PHRASE_RULES)
    assert get_profile("10-K").healing_rules == expected


def test_cover_table_cleaners_configuration() -> None:
    assert get_profile("10-K").cover_table_cleaners == ("report_period",)
    assert get_profile("20-F").cover_table_cleaners == ("report_period",)
    assert get_profile("10-Q").cover_table_cleaners == ("report_period",)
    assert get_profile("8-K").cover_table_cleaners == ()
    assert get_profile("GENERIC").cover_table_cleaners == ()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("10-K/A", "10-K"),
        ("10-K405/A", "10-K"),
        ("10-QSB", "10-Q"),
        ("8-K12B", "8-K"),
        ("6-K/A", "6-K"),
        ("20FR12B", "20-F"),
        ("10-q", "10-Q"),
        ("S-1", "GENERIC"),
        ("", "GENERIC"),
    ],
)
def test_get_profile_resolves_canonical_family(raw: str, expected: str) -> None:
    assert get_profile(raw) is COVER_PROFILES[expected]


def test_get_profile_is_case_insensitive_for_unaliased_names() -> None:
    assert get_profile("generic") is COVER_PROFILES["GENERIC"]


def test_label_groups_are_the_canonical_cover_captions() -> None:
    assert COMMON_COVER_LABELS == COVER_LABELS_FLAT
    assert ANNUAL_COVER_LABELS == COMMON_COVER_LABELS
    assert QUARTERLY_COVER_LABELS == COMMON_COVER_LABELS
    assert NO_COVER_LABELS == COMMON_COVER_LABELS


def test_phrase_rule_groups() -> None:
    assert QUARTERLY_PHRASE_RULES == tuple(COMMON_PHRASE_RULES)
    assert NO_COVER_PHRASE_RULES == tuple(COMMON_PHRASE_RULES)


@pytest.mark.parametrize("family", (*COVER_FAMILIES, *NO_COVER_FAMILIES))
def test_evidence_terms_mirror_the_cover_shape_terms(family: str) -> None:
    profile = get_profile(family)
    assert profile.evidence_terms == profile.cover_evidence.shape_terms


def test_annual_cover_evidence_is_composed_from_the_common_vocabulary() -> None:
    annual = AnnualReportEvidence()
    cover = get_profile("10-K").cover_evidence
    assert cover.identity_terms == COVER_START_IDENTITY_TERMS
    assert cover.labels == COMMON_COVER_LABELS
    assert cover.shape_terms == (
        *COMMON_COVER_LABELS,
        *COVER_EVIDENCE_TERMS,
        *annual.shape_terms,
    )
    assert cover.cover_end_terms == annual.incorporated_reference_terms
    assert cover.healing_rules == annual.healing_rules


def test_quarterly_cover_evidence_has_no_incorporated_reference_end() -> None:
    cover = get_profile("10-Q").cover_evidence
    assert cover.identity_terms == COVER_START_IDENTITY_TERMS
    assert cover.shape_terms == (*COMMON_COVER_LABELS, "section 12(b)")
    assert cover.labels == COMMON_COVER_LABELS
    assert cover.cover_end_terms == ()
    assert cover.healing_rules == ()


def test_annual_body_anchors_start_earlier_than_quarterly() -> None:
    annual = get_profile("10-K").body_evidence
    quarterly = get_profile("10-Q").body_evidence
    # Annual covers all SEC Items 1-15 (plus sub-items) to handle 10-K/A amendments.
    assert "PART I" in annual.structural_headings
    assert "ITEM 1" in annual.structural_headings
    assert "ITEM 15" in annual.structural_headings
    assert len(annual.structural_headings) > 3
    assert quarterly.structural_headings == ("PART I", "ITEM 1")
    assert annual.cover_terms != ()
    assert quarterly.cover_terms != ()


def test_current_report_body_anchors_on_the_eight_k_item_list() -> None:
    body = get_profile("8-K").body_evidence
    assert body.structural_headings == tuple(d.item for d in FORM_8K_ITEMS)
    assert "signature" in body.semantic_headings
    assert "item" in body.semantic_headings


def test_6_k_body_evidence_drops_item_headings_for_foreign_ones() -> None:
    eight_k = get_profile("8-K").body_evidence
    six_k = get_profile("6-K").body_evidence
    assert six_k.structural_headings == ()
    assert six_k.semantic_headings == (
        "signatures",
        "signature",
        "exhibit",
        "press release",
        *FORWARD_LOOKING_PHRASES,
    )
    assert six_k.body_ngrams == eight_k.body_ngrams
    assert six_k.body_verbs == eight_k.body_verbs
    assert six_k.body_terms == eight_k.body_terms
    assert six_k.lexical == eight_k.lexical


def test_generic_profile_declares_baseline_body_evidence() -> None:
    body = get_profile("GENERIC").body_evidence
    assert body.structural_headings == ()
    assert body.semantic_headings == FORWARD_LOOKING_PHRASES
    assert body.body_ngrams == ()
    assert body.body_verbs == ()
    assert body.body_terms == ()
    assert body.cover_terms == ()


@pytest.mark.parametrize("family", LEXICAL_FAMILIES)
def test_family_profiles_attach_an_explicit_lexical_pack(family: str) -> None:
    """`derive_lexical_pack` drops the forward, header, general, and soft tiers the
    backward body search scores against, so a fallback scores wrongly.
    """
    lexical = get_profile(family).body_evidence.lexical
    assert lexical is not None
    assert isinstance(lexical, LexicalEvidencePack)
    assert lexical.tiers


def test_generic_profile_declares_no_lexical_pack() -> None:
    assert get_profile("GENERIC").body_evidence.lexical is None


@pytest.mark.parametrize(
    ("family", "expected"),
    [
        ("10-K", "annual_body_start"),
        ("20-F", "annual_body_start"),
        ("10-Q", "quarterly_body_start"),
        ("8-K", "current_body_start"),
        ("6-K", "current_body_start"),
    ],
)
def test_lexical_pack_identity_per_family(family: str, expected: str) -> None:
    assert get_profile(family).body_evidence.lexical.name == expected


@pytest.mark.parametrize(
    ("family", "expected"),
    [
        ("10-K", FORM_10K_DERIVED),
        ("20-F", FORM_20F_DERIVED),
        ("10-Q", FORM_10Q_DERIVED),
        ("8-K", None),
        ("6-K", None),
        ("GENERIC", None),
    ],
)
def test_derived_taxonomy_is_attached_per_family(family: str, expected: object) -> None:
    assert get_profile(family).derived_taxonomy is expected


def test_checkbox_schema_is_attached_only_to_cover_bearing_families() -> None:
    assert get_profile("10-K").checkbox_schema is ANNUAL_CHECKBOX_SCHEMA
    assert get_profile("20-F").checkbox_schema is ANNUAL_CHECKBOX_SCHEMA
    assert get_profile("10-Q").checkbox_schema is QUARTERLY_CHECKBOX_SCHEMA
    for family in NO_COVER_FAMILIES:
        assert get_profile(family).checkbox_schema is None


def test_builders_compose_the_registry_entries() -> None:
    annual = build_annual_profile("10-K")
    assert isinstance(annual, CoverProfile)
    assert annual.family == "10-K"
    assert annual.labels == ANNUAL_COVER_LABELS

    quarterly = build_quarterly_profile("10-Q")
    assert quarterly.labels == QUARTERLY_COVER_LABELS
    assert quarterly.healing_rules == QUARTERLY_PHRASE_RULES

    current = build_current_profile("8-K")
    assert current.boundary is not None
    assert current.labels == COMMON_COVER_LABELS

    generic = build_no_cover_profile("S-1")
    assert generic.boundary is not None
    assert generic.healing_rules == tuple(COMMON_PHRASE_RULES)
    assert generic.cover_evidence is not None
    assert generic.cover_evidence.shape_terms == COMMON_COVER_LABELS


def test_builders_leave_taxonomy_attachment_to_the_registry() -> None:
    assert build_annual_profile("10-K").derived_taxonomy is None
    assert build_quarterly_profile("10-Q").derived_taxonomy is None
    assert build_current_profile("8-K").derived_taxonomy is None


@pytest.mark.parametrize("family", (*COVER_FAMILIES, *NO_COVER_FAMILIES))
def test_every_registry_profile_compiles_boundary_rules(family: str) -> None:
    profile = get_profile(family)
    rules = compile_cover_rules(profile.cover_evidence, profile.body_evidence)
    assert rules.cover_start_shape.pattern
    assert rules.cover_identity.pattern


@pytest.mark.parametrize("family", COVER_FAMILIES)
def test_cover_bearing_profiles_enable_every_signal_but_incorporated_reference(
    family: str,
) -> None:
    policy = get_profile(family).boundary
    assert policy is not None
    # INCORPORATED_REFERENCE is excluded only for quarterly families and
    # AMENDMENT_TRANSITION only for annual ones.
    expected = set(BoundarySignal) - {BoundarySignal.INCORPORATED_REFERENCE}
    if family in ("10-K", "20-F"):
        expected.add(BoundarySignal.INCORPORATED_REFERENCE)
    else:
        expected.discard(BoundarySignal.AMENDMENT_TRANSITION)
    assert set(policy.signals) == expected
