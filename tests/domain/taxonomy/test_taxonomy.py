"""Reference data the company-family engine depends on: membership, immutability,
and the cases where stripping must not happen.
"""

from __future__ import annotations

from types import MappingProxyType

import pytest

from edgar_sec.domain.taxonomy.family_vocab import (
    ABBR_MAP,
    AMBIGUOUS_POSTAL_CODES,
    CONTEXT_RULES,
    CORPORATE_DESIGNATORS,
    FAMILY_INDEX_SCHEMA_VERSION,
    IDENTITY_NOUNS,
    INSTITUTION_ALIASES,
    MIN_SQUASH_CHARS,
    ORDINAL_WORDS,
    PLURAL_MAP,
    SPONSOR_BOUNDARY_WORDS,
    SPV_MARKERS,
    SPV_PREFIX,
    ENTITY_PREFIX,
    CIK_PREFIX,
    rule_fingerprint_payload,
    strippable_postal_codes,
)
from edgar_sec.domain.taxonomy.jurisdictions import (
    JURISDICTION_RE,
    STATE_NAMES,
    STATE_POSTAL_CODES,
    clean_entity_name,
    strip_jurisdiction,
)
from edgar_sec.domain.taxonomy.legal_forms import (
    LEGAL_FORMS,
    NAME_STOPWORDS,
    entity_name_tokens,
)

# --- jurisdictions --------------------------------------------------------


def test_postal_code_membership_is_complete() -> None:
    """Fifty states, DC, and the three EDGAR territories."""
    assert len(STATE_POSTAL_CODES) == 54
    for code in ("CA", "DE", "NY", "WY", "DC", "PR", "VI", "GU"):
        assert code in STATE_POSTAL_CODES
    assert "XX" not in STATE_POSTAL_CODES


def test_state_names_cover_every_postal_code() -> None:
    """Each code must have a spelled-out name, or stripping is guesswork."""
    assert len(STATE_NAMES) == len(STATE_POSTAL_CODES)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("APPLE INC/CA", "APPLE INC"),
        ("ACME CORP/DE", "ACME CORP"),
        ("SMITH LLC/NY/", "SMITH LLC"),
        ("ACME INC / TX", "ACME INC"),
        ("ACME inc/ca", "ACME inc"),
    ],
)
def test_strip_jurisdiction(raw: str, expected: str) -> None:
    assert strip_jurisdiction(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "ACME INC/ZZ",  # not a postal code
        "ACME / HOLDING",  # slash is not a jurisdiction delimiter
        "ACME INC",  # no suffix at all
        "ACME INC/CALIFORNIA",  # spelled out, not a code
    ],
)
def test_strip_jurisdiction_leaves_non_codes_alone(raw: str) -> None:
    assert strip_jurisdiction(raw) == raw


def test_jurisdiction_regex_is_case_insensitive_and_anchored() -> None:
    assert JURISDICTION_RE.search("X/CA") is not None
    assert JURISDICTION_RE.search("X/ca") is not None
    # a code mid-string with no delimiter is not a jurisdiction
    assert JURISDICTION_RE.search("XCA") is None


def test_clean_entity_name_collapses_whitespace() -> None:
    assert clean_entity_name("  ACME   INC/CA  ") == "ACME INC"


# --- legal forms ----------------------------------------------------------


def test_legal_forms_cover_us_and_foreign_issuers() -> None:
    for form in ("inc", "corp", "llc", "lp", "gmbh", "sa", "ag", "pte"):
        assert form in LEGAL_FORMS or form == "pte", form
    for form in ("inc", "llc", "gmbh", "s.a."):
        assert form in LEGAL_FORMS


def test_legal_forms_excludes_words_that_carry_identity() -> None:
    """Stripping a descriptive word would merge unrelated companies."""
    for word in ("bank", "airlines", "motors", "energy", "systems", "pharma"):
        assert word not in LEGAL_FORMS, word


def test_entity_type_words_are_treated_as_legal_forms() -> None:
    """One registrant family: "ACME HOLDINGS" and "ACME" are the same."""
    for word in ("holding", "holdings", "group", "grp", "trust", "fund"):
        assert word in LEGAL_FORMS, word


def test_name_stopwords_include_the_ampersand() -> None:
    assert "&" in NAME_STOPWORDS
    assert "the" in NAME_STOPWORDS


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Apple Inc.", ["apple"]),
        ("The Acme Corporation", ["acme"]),
        ("ACME & SONS, LLC", ["acme", "sons"]),
        ("A B Corp", []),  # single characters carry no identity
        ("First Data Corporation", ["first", "data"]),
    ],
)
def test_entity_name_tokens(raw: str, expected: list[str]) -> None:
    assert entity_name_tokens(raw) == expected


def test_entity_name_tokens_drops_the_jurisdiction_first() -> None:
    assert entity_name_tokens("Apple Inc/CA") == ["apple"]


# --- family vocabulary ----------------------------------------------------


def test_the_namespace_prefixes_cannot_collide() -> None:
    """A sponsor and its own SPVs are different families by construction, not by luck."""
    assert len({SPV_PREFIX, ENTITY_PREFIX, CIK_PREFIX}) == 3
    assert all(":" in p for p in (SPV_PREFIX, ENTITY_PREFIX, CIK_PREFIX))


def test_tables_are_immutable() -> None:
    """A caller must not be able to corrupt shared reference data."""
    for table in (
        ABBR_MAP,
        CONTEXT_RULES,
        PLURAL_MAP,
        ORDINAL_WORDS,
        INSTITUTION_ALIASES,
    ):
        assert isinstance(table, MappingProxyType)
    for table in (
        SPV_MARKERS,
        SPONSOR_BOUNDARY_WORDS,
        CORPORATE_DESIGNATORS,
        IDENTITY_NOUNS,
        AMBIGUOUS_POSTAL_CODES,
        LEGAL_FORMS,
        STATE_POSTAL_CODES,
    ):
        assert isinstance(table, frozenset)
    with pytest.raises(TypeError):
        ABBR_MAP["x"] = "y"  # type: ignore[index]
    with pytest.raises(TypeError):
        CONTEXT_RULES["x"] = ("y", frozenset(), frozenset())  # type: ignore[index]
    with pytest.raises(TypeError):
        PLURAL_MAP["x"] = "y"  # type: ignore[index]
    with pytest.raises(TypeError):
        INSTITUTION_ALIASES["x"] = "y"  # type: ignore[index]
    # frozenset has no mutating methods at all
    for method in ("add", "update", "discard", "remove", "pop", "clear"):
        assert not hasattr(SPV_MARKERS, method), method


def test_context_rule_neighbour_sets_are_immutable() -> None:
    for expansion, prev, nxt in CONTEXT_RULES.values():
        assert isinstance(prev, frozenset)
        assert isinstance(nxt, frozenset)
        assert isinstance(expansion, str)


def test_ambiguous_abbreviations_are_excluded_from_abbr_map() -> None:
    """An ambiguous token expanded blindly would corrupt unrelated names."""
    for token in ("com", "comm", "ps", "bk", "as", "tr", "ct", "sr", "se", "srs"):
        assert token in CONTEXT_RULES, token
        assert token not in ABBR_MAP, token


def test_context_rules_name_both_neighbours() -> None:
    """A rule with no constraint on either side would be unconditional."""
    for token, (expansion, prev, nxt) in CONTEXT_RULES.items():
        assert expansion, token
        assert prev or nxt, f"{token} constrains neither neighbour"


def test_unambiguous_abbreviations_resolve() -> None:
    assert ABBR_MAP["mtg"] == "mortgage"
    assert ABBR_MAP["thru"] == "through"
    assert ABBR_MAP["crt"] == "certificate"
    assert ABBR_MAP["bkd"] == "backed"
    assert ABBR_MAP["nts"] == "notes"


def test_plural_map_folds_the_two_that_matter_most() -> None:
    assert PLURAL_MAP["securities"] == "security"
    assert PLURAL_MAP["equities"] == "equity"
    assert PLURAL_MAP["certificates"] == "certificate"


def test_every_spv_marker_is_also_a_sponsor_boundary() -> None:
    """Otherwise a marker could classify an SPV without locating its sponsor."""
    assert SPV_MARKERS <= SPONSOR_BOUNDARY_WORDS


def test_ordinary_entity_nouns_are_not_spv_markers() -> None:
    """`bank`, `company`, `capital`, and `fund` name the sponsor, not a vehicle."""
    for word in ("bank", "company", "capital", "fund", "insurance", "ventures"):
        assert word not in SPV_MARKERS, word


def test_identity_nouns_are_never_designators() -> None:
    """Stripping `trust` is what reduced `American Trust 2013-1` to `american`."""
    assert not (IDENTITY_NOUNS & CORPORATE_DESIGNATORS)


def test_an_institution_alias_value_carries_no_marker_its_variant_lacks() -> None:
    """A fold that introduced a marker would move a registrant between namespaces."""
    for squashed, canonical in INSTITUTION_ALIASES.items():
        assert canonical == canonical.strip()
        assert canonical and " " not in canonical, (squashed, canonical)
        assert not (set(canonical.split()) & SPV_MARKERS), (squashed, canonical)


def test_strippable_postal_codes_exclude_the_ambiguous_words() -> None:
    codes = strippable_postal_codes()
    assert codes == frozenset(codes)
    assert not (codes & AMBIGUOUS_POSTAL_CODES)
    assert "tx" in codes and "co" not in codes
    assert len(codes | AMBIGUOUS_POSTAL_CODES) == len(STATE_POSTAL_CODES)


def test_the_rule_fingerprint_covers_every_table_that_moves_a_key() -> None:
    """An unlisted table would change family keys without changing the cache id."""
    payload = rule_fingerprint_payload()
    assert payload["schema_version"] == FAMILY_INDEX_SCHEMA_VERSION
    for key in (
        "spv_markers",
        "boundary_words",
        "aliases",
        "abbreviations",
        "plurals",
        "ordinals",
        "designators",
        "identity_nouns",
        "postal_codes",
    ):
        assert payload[key], key


def test_the_squash_floor_is_enforced() -> None:
    """A short concatenation collides by accident too often to trust."""
    assert MIN_SQUASH_CHARS >= 6
