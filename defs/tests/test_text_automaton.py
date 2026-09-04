"""Tests for the token-level Aho-Corasick multi-pattern automaton."""

from __future__ import annotations

from defs.taxonomy.tables.shapes import ShapeConstraint
from defs.taxonomy.tables.specs import TableFamilySpec, TableScope
from defs.text.automaton import (
    compile_family_automaton,
    compile_lexical_matcher,
)
from defs.text.bow import (
    EvidenceTier,
    LexicalEvidencePack,
    compile_evidence_pack,
    tokenize,
)


def _make_spec(
    name: str,
    required: tuple[str, ...],
    supporting: tuple[str, ...] = (),
    exclusions: tuple[str, ...] = (),
) -> TableFamilySpec:
    tiers = [
        EvidenceTier(
            name="required",
            priority=2,
            value=3,
            terms=required,
            match_kind="ngram",
            min_distinct_hits=1,
        )
    ]
    if supporting:
        tiers.append(
            EvidenceTier(
                name="supporting",
                priority=1,
                value=1,
                terms=supporting,
                match_kind="ngram",
                min_distinct_hits=1,
                support=True,
            )
        )
    pack = compile_evidence_pack(
        LexicalEvidencePack(
            name=f"{name}_pack",
            tiers=tuple(tiers),
            exclusion_terms=exclusions,
        )
    )
    return TableFamilySpec(
        name=name,
        shape=ShapeConstraint(),
        evidence_pack=pack,
        candidate_default_scope=TableScope.BODY,
    )


def test_automaton_single_and_multi_word_matches() -> None:
    spec1 = _make_spec(
        "derivatives", ("interest rate swaps", "foreign exchange contracts")
    )
    spec2 = _make_spec("equity", ("retained earnings", "common stock"))

    automaton = compile_family_automaton([spec1, spec2])
    tokens = tokenize("We hold interest rate swaps and common stock as of year end.")

    matches = automaton.scan_tokens(tokens)
    terms = [payload.term for _, payload in matches]
    assert "interest rate swaps" in terms
    assert "common stock" in terms


def test_automaton_family_hits_aggregation() -> None:
    spec1 = _make_spec(
        "derivatives", ("interest rate swaps",), ("hedging instruments",)
    )
    spec2 = _make_spec("equity", ("retained earnings",), exclusions=("derivative",))

    automaton = compile_family_automaton([spec1, spec2])
    tokens = tokenize(
        "Our hedging instruments include interest rate swaps under derivative rules."
    )

    hits = automaton.scan_family_hits(tokens)
    assert "derivatives" in hits
    assert "required" in hits["derivatives"]
    assert "supporting" in hits["derivatives"]
    assert "interest rate swaps" in hits["derivatives"]["required"]
    assert "hedging instruments" in hits["derivatives"]["supporting"]

    # Verify exclusion hit tagged for equity
    assert "equity" in hits
    assert "_exclusion" in hits["equity"]
    assert "derivative" in hits["equity"]["_exclusion"]


def test_automaton_failure_fallback_partial_overlap() -> None:
    # Test failure link transitions where a prefix matches but diverges
    spec = _make_spec("rates", ("interest rate swap", "rate swap floating"))
    automaton = compile_family_automaton([spec])

    tokens = tokenize("The interest interest rate swap floating agreement.")
    matches = automaton.scan_tokens(tokens)
    terms = [payload.term for _, payload in matches]
    assert "interest rate swap" in terms
    assert "rate swap floating" in terms


def test_lexical_matcher_declarative_dictionary() -> None:
    matcher = compile_lexical_matcher(
        {
            "forward_looking": (
                "cautionary statement",
                "forward-looking statements",
                "safe harbor",
                "private securities litigation reform act",
            ),
            "audit_opinion": (
                "report of independent registered public accounting firm",
                "basis for opinion",
                "critical audit matters",
            ),
            "item_heading": (
                "item 1. business",
                "item 1a. risk factors",
                "item 7. management's discussion",
            ),
        }
    )

    sample_prose = (
        "This Annual Report contains forward-looking statements within the "
        "meaning of the Private Securities Litigation Reform Act of 1995."
    )

    # 1. Fast boolean check
    assert matcher.has_any(sample_prose)
    assert matcher.has_any(sample_prose, ["forward_looking"])
    assert not matcher.has_any(sample_prose, ["audit_opinion"])

    # 2. Classification
    result = matcher.classify(sample_prose)
    assert result.category == "forward_looking"
    assert result.score == 3
    assert "forward-looking statements" in result.matched_terms
    assert "private securities litigation reform act" in result.matched_terms

    # 3. Find matched term locations
    matches = matcher.find_matches(sample_prose)
    matched_phrases = [m.term for m in matches]
    assert "forward-looking statements" in matched_phrases
    assert "private securities litigation reform act" in matched_phrases
