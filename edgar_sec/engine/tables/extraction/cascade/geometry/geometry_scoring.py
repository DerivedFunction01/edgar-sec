"""Family scoring: signature profiles scored over a geometry.

score_geometry prices every family's profile over the channel
text, folds form-test outcomes, and applies scored vetoes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

from edgar_sec.engine.tables.extraction.cascade.geometry.detail_signatures import (
    SCORED_VETOES,
    detail_signatures,
)
from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_text import (
    GeometryText,
)
from edgar_sec.engine.tables.extraction.core.term_index import (
    TermEntry,
    TermIndex,
    term_present as term_present,
)
from edgar_sec.engine.tables.extraction.core.text.normalize import normalize_text
from edgar_sec.engine.tables.extraction.core.subjects.signature_profiles import (
    CHANNEL_WEIGHTS,
    SIGNATURE_TERMS,
    ContainmentEdge,
    SignatureTerm,
)
from edgar_sec.engine.tables.extraction.vetoes.term_vetoes import term_veto_hits

# False-claim constants, derivation-priced. Vetoes are
# scored negative evidence only — the
# Deliverable 1 pricing earned no hard veto anywhere.
VETO_POINTS = 1.5


@dataclass(frozen=True, slots=True)
class ClaimEvidence:
    """One scored contribution to a family's claim."""

    channel: str
    detail: str
    points: float


@dataclass(frozen=True, slots=True)
class FamilyScore:
    """A family's profile score over one geometry, by channel."""

    family: str
    total: float
    by_channel: dict[str, float]
    evidence: tuple[ClaimEvidence, ...]


@dataclass(frozen=True, slots=True)
class ClaimGroup:
    """One family's grouped scored return over a geometry."""

    family: str
    score: float
    state: str
    role: str
    channels: dict[str, float]
    veto_flags: tuple[str, ...]
    explained_foreign: float


@dataclass(frozen=True, slots=True)
class CompetitionResult:
    """Claiming outcome: claims, contested pairs, and the scores."""

    claims: tuple[str, ...]
    contested: tuple[str, ...]
    scores: dict[str, FamilyScore]
    foreign_explained: dict[str, float] = field(default_factory=dict)
    groups: tuple[ClaimGroup, ...] = ()


_HIT = "hit"


@lru_cache(maxsize=None)
def _channel_index(terms: tuple[SignatureTerm, ...], channel: str) -> TermIndex:
    """One unified index over a channel's signature terms.

    Match mode is the per-term scan's own: word-boundary for a
    term with no space or hyphen, literal substring otherwise.
    """
    return TermIndex(
        TermEntry(spec.term, _HIT, word=" " not in spec.term and "-" not in spec.term)
        for spec in terms
        if spec.channel == channel
    )


def _signature_hits(
    terms: tuple[SignatureTerm, ...], texts: dict[str, str]
) -> dict[str, frozenset[str]]:
    """Collected matches per channel: one traversal per text."""
    hits: dict[str, frozenset[str]] = {}
    for spec in terms:
        if spec.channel not in hits:
            hits[spec.channel] = (
                _channel_index(terms, spec.channel)
                .scan(texts[spec.channel])
                .get(_HIT, frozenset())
            )
    return hits


def score_geometry(
    geometry: GeometryText,
    terms: tuple[SignatureTerm, ...] = SIGNATURE_TERMS,
) -> dict[str, FamilyScore]:
    """Score every family's signature profile over the geometry."""
    texts = {
        "caption": normalize_text(geometry.caption),
        "leadin": normalize_text(geometry.leadin),
        "notehead": normalize_text(geometry.notehead),
        "lead_title": normalize_text(geometry.lead_title),
        "stub": geometry.stub_text,
    }
    by_family: dict[str, dict[str, float]] = {}
    evidence: dict[str, list[ClaimEvidence]] = {}
    hits = _signature_hits(terms, texts)
    for spec in terms:
        if spec.term not in hits[spec.channel]:
            continue
        points = spec.weight * CHANNEL_WEIGHTS[spec.channel]
        by_family.setdefault(spec.family, {}).setdefault(spec.channel, 0.0)
        by_family[spec.family][spec.channel] += points
        evidence.setdefault(spec.family, []).append(
            ClaimEvidence(spec.channel, spec.term, points)
        )
    scores: dict[str, FamilyScore] = {}
    for family, channels in by_family.items():
        total = sum(channels.values())
        scores[family] = FamilyScore(
            family, total, dict(channels), tuple(evidence[family])
        )
    for outcome in geometry.form_tests:
        entry = ClaimEvidence(
            "form_test",
            f"{outcome.test_id} {'passed' if outcome.passed else 'failed'}",
            outcome.points if outcome.passed else 0.0,
        )
        score = scores.get(outcome.family)
        if outcome.passed:
            if score is None:
                scores[outcome.family] = FamilyScore(
                    outcome.family,
                    outcome.points,
                    {"form_test": outcome.points},
                    (entry,),
                )
            else:
                channels = dict(score.by_channel)
                channels["form_test"] = channels.get("form_test", 0.0) + outcome.points
                scores[outcome.family] = FamilyScore(
                    outcome.family,
                    score.total + outcome.points,
                    channels,
                    score.evidence + (entry,),
                )
        elif outcome.evaluable and score is not None:
            scores[outcome.family] = FamilyScore(
                outcome.family,
                score.total,
                dict(score.by_channel),
                score.evidence + (entry,),
            )
    fired = detail_signatures(geometry)
    for family, signatures in SCORED_VETOES.items():
        score = scores.get(family)
        if score is None:
            continue
        hits = [s for s in signatures if s in fired]
        if not hits:
            continue
        penalty = VETO_POINTS * len(hits)
        trail = score.evidence + tuple(
            ClaimEvidence("veto", name, -VETO_POINTS) for name in hits
        )
        channels = dict(score.by_channel)
        channels["veto"] = channels.get("veto", 0.0) - penalty
        scores[family] = FamilyScore(
            family, max(score.total - penalty, 0.0), channels, trail
        )
    # Term vetoes, scored tier (Step 6 v2 re-price): any-hit —
    # one VETO_POINTS penalty per family per claim, however
    # many of the family's scored terms hit in either channel.
    for family, tiers in term_veto_hits(geometry).items():
        term = tiers.get("scored")
        if term is None:
            continue
        score = scores.get(family)
        if score is None:
            continue
        trail = score.evidence + (ClaimEvidence("veto", f"term:{term}", -VETO_POINTS),)
        channels = dict(score.by_channel)
        channels["veto"] = channels.get("veto", 0.0) - VETO_POINTS
        scores[family] = FamilyScore(
            family, max(score.total - VETO_POINTS, 0.0), channels, trail
        )
    return scores


def _explained_foreign(
    claimant: str,
    scores: dict[str, FamilyScore],
    edges: tuple[ContainmentEdge, ...],
) -> tuple[float, dict[str, float]]:
    """Foreign mass after containment explanation, and the explained part."""
    raw = 0.0
    effective = 0.0
    explained: dict[str, float] = {}
    for family, score in scores.items():
        if family == claimant:
            continue
        raw += score.total
        discount = 0.0
        for edge in edges:
            if edge.subset == family and edge.parent == claimant:
                discount = max(discount, edge.discount)
            if edge.subset == claimant and edge.parent == family:
                discount = max(discount, edge.discount)
        effective += score.total * (1.0 - discount)
        if discount and score.total:
            explained[family] = score.total * discount
    return effective, explained
