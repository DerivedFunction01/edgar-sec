"""Contract tests for compiled cover rules."""

from __future__ import annotations

from edgar_sec.domain.forms.common.models import BodyEvidencePack
from edgar_sec.engine.forms.cover.rules import compile_cover_rules

_BODY = BodyEvidencePack(
    structural_headings=("PART I", "ITEM 1"),
    semantic_headings=("risk factors", "properties"),
    body_ngrams=("market segments", "labor union"),
    body_verbs=("provides", "operates"),
    body_terms=("founded", "provider"),
    cover_terms=("registrant",),
)

# ``compile_cover_rules`` keys its cache on ``id()`` of the evidence objects,
# so every pack handed to it must stay alive for the process or a recycled
# address would return another pack's compiled rules. Module scope keeps
# each one alive for the whole module.
_EMPTY_COVER = type(
    "Cover", (), {"labels": (), "identity_terms": (), "shape_terms": ()}
)()
_CUSTOM_COVER = type(
    "Cover",
    (),
    {
        "labels": ("prose witness",),
        "identity_terms": ("annual report",),
        "shape_terms": ("sole registrant",),
        "cover_end_terms": ("documents incorporated by reference",),
    },
)()


def test_compile_without_evidence_uses_the_default_cover_vocabulary() -> None:
    rules = compile_cover_rules()

    assert rules.cover_start_identity.search("SECURITIES AND EXCHANGE COMMISSION")
    assert rules.cover_start_shape.search(
        "Securities registered pursuant to Section 12(b)"
    )
    assert rules.cover_identity.search("FORM 10-K")


def test_empty_vocabulary_compiles_to_a_never_matching_expression() -> None:
    rules = compile_cover_rules(cover_evidence=_EMPTY_COVER, body_evidence=_BODY)

    assert rules.incorporated.search("anything") is None


def test_profile_vocabulary_replaces_the_defaults() -> None:
    rules = compile_cover_rules(cover_evidence=_CUSTOM_COVER, body_evidence=_BODY)

    assert rules.cover_start_identity.search("ANNUAL REPORT [X]")
    assert rules.incorporated.search("documents incorporated by reference")
    assert rules.cover_start_shape.search("sole registrant")


def test_lexical_pack_is_derived_from_flat_body_vocabulary() -> None:
    rules = compile_cover_rules(body_evidence=_BODY)

    assert rules.lexical.name == "derived_body"
    assert tuple(tier.name for tier in rules.lexical.tiers) == (
        "body_phrase",
        "body_strong",
        "body_weak",
    )
    assert rules.lexical.band_max_value == (3, 2, 1)
    assert "registrant" in rules.lexical.exclusions


def test_explicit_lexical_pack_wins_over_derived_vocabulary() -> None:
    from edgar_sec.foundation.text.evidence import EvidenceTier, LexicalEvidencePack

    explicit = LexicalEvidencePack(
        name="explicit",
        tiers=(
            EvidenceTier(
                name="only",
                priority=10,
                value=1,
                terms=("alpha",),
            ),
        ),
    )
    body = BodyEvidencePack(body_terms=("founded",), lexical=explicit)
    rules = compile_cover_rules(body_evidence=body)

    assert rules.lexical.name == "explicit"
    assert tuple(tier.name for tier in rules.lexical.tiers) == ("only",)


def test_results_are_cached_by_evidence_identity() -> None:
    first = compile_cover_rules(body_evidence=_BODY)
    second = compile_cover_rules(body_evidence=_BODY)

    assert first is second


def test_body_semantic_expression_matches_profile_headings() -> None:
    rules = compile_cover_rules(body_evidence=_BODY)

    assert rules.body_semantic.search("RISK FACTORS")
    assert rules.body_semantic.search("Properties") is not None
    assert rules.body_semantic.search("unrelated section title") is None
