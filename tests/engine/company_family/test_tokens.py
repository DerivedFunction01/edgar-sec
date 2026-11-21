"""Token normalization for family assignment: identity stems, SPV marking, and the
umbrella phrase. Not family keys, which are assigned from the universe as a whole.
"""

from __future__ import annotations

import pytest

from edgar_sec.engine.company_family.tokens import (
    apply_aliases,
    contains_umbrella,
    has_spv_marker,
    identity_tokens,
    is_identifier,
    normalize_tokens,
    normalized_key,
    sponsor_candidate,
    umbrella_parent,
)


def stem(name: str) -> str:
    return " ".join(identity_tokens(name))


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("", []),
        ("   ", []),
        ("/DE/", []),
        ("RBS CAPITAL LP II", ["rbs", "capital"]),
        ("RBS CAPITAL LP", ["rbs", "capital"]),
        ("SMARTTRUST 455", ["smarttrust"]),
        ("HONDA MOTOR CO LTD", ["honda", "motor"]),
        ("WELLS FARGO & CO", ["wells", "fargo"]),
    ],
)
def test_identity_stems(raw: str, expected: list[str]) -> None:
    assert identity_tokens(raw) == expected


def test_a_legal_form_before_a_deal_marker_is_still_reached() -> None:
    """The peel alternates, so `LP II` and `LP` cannot land in different families."""
    assert stem("RBS CAPITAL LP II") == stem("RBS CAPITAL LP")


def test_a_brand_is_not_reduced_to_its_legal_form() -> None:
    """`V.I.A.` keeps its initials; a stem of only designators carries no identity."""
    assert identity_tokens("V.I.A. CORP.") == []
    assert stem("V.I.A. CORP.") == ""


def test_identity_nouns_survive_anywhere_in_a_name() -> None:
    """Stripping `trust` is what reduced `American Trust 2013-1` to `american`."""
    for noun in ("trust", "fund", "group", "holding", "bancorp"):
        assert noun in identity_tokens(f"ACME {noun.upper()} 2013-1")


def test_an_interior_legal_form_is_kept_but_a_trailing_one_is_peeled() -> None:
    """Only the tail is designator furniture; `NV ENERGY` keeps its `nv` stem."""
    assert identity_tokens("SL GREEN REALTY CORP") == ["sl", "green", "realty"]
    assert identity_tokens("NV ENERGY, INC.") == ["energy"]


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("J.P. Morgan Chase Commercial Mtg Sec Tr 2011-C5", "mortgage"),
        ("Santander Drive Auto Receivables LLC", "receivable"),
    ],
)
def test_abbreviations_expand(raw: str, expected: str) -> None:
    assert expected in normalize_tokens(raw)


def test_an_ambiguous_abbreviation_expands_only_in_context() -> None:
    assert "trust" not in normalize_tokens("trading volume analytics")
    assert "trust" in normalize_tokens("Some Commercial Mortgage Pass Through Trust")


def test_full_state_names_are_not_stripped() -> None:
    """Maryland and Kansas are distinct issuers, not one tax-exempt trust."""
    assert stem("MARYLAND TAX EXEMPT TRUST") != stem("KANSAS TAX EXEMPT TRUST")


def test_postal_codes_are_stripped_but_ambiguous_ones_are_kept() -> None:
    """`me` and `pa` are words as often as state codes, so stripping them corrupts."""
    assert identity_tokens("ACME CAPITAL TX") == ["acme", "capital"]
    assert identity_tokens("ACME ME 153") == ["acme", "me"]
    assert identity_tokens("ACME PA 153") == ["acme", "pa"]


def test_a_surname_plural_is_not_folded() -> None:
    """EDGAR carries individuals as `SURNAME FIRSTNAME`, so folding merges people."""
    assert stem("WOODS MICHAEL") != stem("WOOD MICHAEL")
    assert stem("OWENS WILLIAM") != stem("OWEN WILLIAM")


@pytest.mark.parametrize(
    "raw, identifier",
    [
        ("1999", True),
        ("a", True),
        ("c5", True),
        ("xxxi", True),
        ("vii", True),
        ("trust", False),
        ("series", False),
        ("receivable", False),
    ],
)
def test_identifier_detection(raw: str, identifier: bool) -> None:
    assert is_identifier(raw) is identifier


def test_spv_marking_follows_the_issuer_forms() -> None:
    assert has_spv_marker("Honda Auto Receivables 2013-1 Owner Trust")
    assert has_spv_marker("WELLS FARGO MORTGAGE BACKED SECURITIES TRUST SERIES 2005-1")
    assert not has_spv_marker("Honda Motor Co Ltd")
    assert not has_spv_marker("JPMORGAN CHASE & CO")


def test_a_token_split_alone_cannot_change_the_namespace() -> None:
    """`SMART TRUST` and `SMARTTRUST` are one issuer, and neither is a vehicle."""
    assert normalized_key("SMART TRUST 218") == normalized_key("SMARTTRUST 455")
    assert not has_spv_marker("SMART TRUST 218")
    assert not has_spv_marker("SMARTTRUST 455")


def test_a_reviewed_alias_folds_onto_its_canonical_form() -> None:
    assert apply_aliases("jpmorgan chase") == "jpmorganchase"
    assert apply_aliases("unreviewed brand") == "unreviewed brand"
    assert apply_aliases("") == ""


def test_the_umbrella_phrase_names_a_parent_outright() -> None:
    assert contains_umbrella("DE-0924 FUND II, A SERIES OF ROLL UP VEHICLES, LP")
    assert not contains_umbrella("ROLL UP VEHICLES LP")
    assert not contains_umbrella("")


def test_an_umbrella_parent_may_look_like_a_deal_code() -> None:
    """`CGF2021` is a parent name, so the identifier filter must not eat it."""
    assert (
        umbrella_parent("HAN INTO SOMNAIR SEP 2024 A SERIES OF CGF2021 LLC")
        == "cgf2021"
    )


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Wells Fargo Mortgage Backed Securities Trust 2005-1", "wells fargo"),
        ("Morgan Stanley ABS Capital I Inc. Trust 2007-HE4", "morgan stanley"),
        (
            "JPMorgan Chase Commercial Mortgage Securities Corp Series 2005-LDP3",
            "jpmorgan chase",
        ),
        ("Honda Auto Receivables 2013-1 Owner Trust", "honda"),
        ("Roll Up Vehicles LP", "roll up vehicles"),
    ],
)
def test_sponsor_candidates_stop_at_the_first_boundary_word(
    raw: str, expected: str
) -> None:
    assert sponsor_candidate(raw) == expected


def test_a_sponsor_candidate_never_returns_nothing_for_a_usable_name() -> None:
    """An empty sponsor would silently merge every SPV under the SPV namespace."""
    assert sponsor_candidate("Wells Fargo Mortgage Backed Securities Trust 2005-1")
