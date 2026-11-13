"""Signature competition: scored claiming over signature profiles.

A claim issues only when a family's own profile dominates the
geometry's text and the foreign profile mass is negligible or
explained by a measured containment edge. Closure corroborates.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from edgar_sec.engine.tables.extraction.signature_profiles import (
    CHANNEL_WEIGHTS,
    CONTAINMENT_EDGES,
    PROV_STEP0_LEXICON,
    PROV_STEP1_MINED,
    ContainmentEdge,
    SignatureTerm,
)
from edgar_sec.engine.tables.extraction.signature_terms_leadin import (
    LEADIN_MINED,
)
from edgar_sec.engine.tables.extraction.signature_terms_lexicon import (
    LEXICON_TERMS,
)
from edgar_sec.engine.tables.extraction.signature_terms_stub import (
    STUB_MINED,
)


def _assemble_terms() -> tuple[SignatureTerm, ...]:
    """Assemble the profile from its measured data modules."""
    terms = [
        SignatureTerm(
            family, channel, term, weight, member, foreign, PROV_STEP0_LEXICON
        )
        for family, channel, term, weight, member, foreign in LEXICON_TERMS
    ]
    terms.extend(
        SignatureTerm(family, "stub", term, weight, member, foreign, PROV_STEP1_MINED)
        for family, term, weight, member, foreign in STUB_MINED
    )
    terms.extend(
        SignatureTerm(family, "leadin", term, weight, member, foreign, PROV_STEP1_MINED)
        for family, term, weight, member, foreign in LEADIN_MINED
    )
    return tuple(terms)


SIGNATURE_TERMS: tuple[SignatureTerm, ...] = _assemble_terms()

# Calibration constants, derivation-priced by the Step 1 harness
# over the adjudicated corpora (record: improvement Step 1).
CLAIM_FLOOR = 5.0
DOMINANCE_RATIO = 1.25
FOREIGN_ALLOWANCE = 0.25
CORROBORATION_POINTS = 0.75
INHERITANCE_FACTOR = 0.5
INHERITANCE_MAX_DISTANCE = 3
TIE_POINTS = 1.0
FRAGMENT_MAX_STUBS = 8

_HEADING_NOTE = re.compile(r"notes to|^\s*note\s+\d", re.IGNORECASE)
_HEADING_NUMBERED = re.compile(r"^\d+\.\s+\S")
_WS = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Lowercase, unify quotes/dashes, collapse whitespace."""
    text = (text or "").lower()
    text = text.replace("’", "'").replace("‘", "'")
    text = text.replace("“", '"').replace("”", '"')
    text = text.replace("–", "-").replace("—", "-")
    return _WS.sub(" ", text)


def heading_text(prose_before: str, prose_after: str, caption: str) -> str:
    """Heading lines framing a geometry: note headings and titles."""
    lines: list[str] = []
    for source in (prose_before or "", prose_after or ""):
        for line in source.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if _HEADING_NOTE.search(stripped) or _HEADING_NUMBERED.match(stripped):
                if len(stripped) < 120:
                    lines.append(stripped)
            elif len(stripped) >= 8 and stripped == stripped.upper():
                if any(ch.isalpha() for ch in stripped):
                    lines.append(stripped)
    lines.append(caption or "")
    return normalize(" ".join(lines))


@dataclass(frozen=True, slots=True)
class GeometryText:
    """One geometry's text evidence, by channel, plus context."""

    caption: str = ""
    leadin: str = ""
    notehead: str = ""
    stubs: tuple[str, ...] = ()
    closure_closed: bool | None = None
    note_title: str | None = None
    section_item: str | None = None

    @property
    def stub_text(self) -> str:
        """The stub distribution as one normalized skeleton text."""
        return normalize(" ".join(self.stubs))

    @property
    def is_fragment(self) -> bool:
        """A fragment: few stubs and no caption of its own."""
        return len(self.stubs) <= FRAGMENT_MAX_STUBS and not self.caption.strip()


def geometry_text_from_table(table) -> GeometryText:
    """Build channel text from a TypedTable (duck-typed context)."""
    context = table.context
    caption = " | ".join(list(context.caption_stack) + list(table.caption.titles))
    stubs = tuple(row.label for row in table.rows if row.label)
    note = context.note
    section = context.section
    return GeometryText(
        caption=caption,
        leadin=context.prose_before or "",
        notehead=heading_text(
            context.prose_before or "", context.prose_after or "", caption
        ),
        stubs=stubs,
        note_title=note.title if note else None,
        section_item=section.item if section else None,
    )


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
class CompetitionResult:
    """Claiming outcome: claims, contested pairs, and the scores."""

    claims: tuple[str, ...]
    contested: tuple[str, ...]
    scores: dict[str, FamilyScore]
    foreign_explained: dict[str, float] = field(default_factory=dict)


def _term_present(term: str, text: str) -> bool:
    if " " in term or "-" in term:
        return term in text
    return re.search(r"\b" + re.escape(term) + r"\b", text) is not None


def score_geometry(
    geometry: GeometryText,
    terms: tuple[SignatureTerm, ...] = SIGNATURE_TERMS,
) -> dict[str, FamilyScore]:
    """Score every family's signature profile over the geometry."""
    texts = {
        "caption": normalize(geometry.caption),
        "leadin": normalize(geometry.leadin),
        "notehead": normalize(geometry.notehead),
        "stub": geometry.stub_text,
    }
    by_family: dict[str, dict[str, float]] = {}
    evidence: dict[str, list[ClaimEvidence]] = {}
    for spec in terms:
        text = texts[spec.channel]
        if not text or not _term_present(spec.term, text):
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


def compete(
    geometry: GeometryText,
    terms: tuple[SignatureTerm, ...] = SIGNATURE_TERMS,
    edges: tuple[ContainmentEdge, ...] = CONTAINMENT_EDGES,
    scores: dict[str, FamilyScore] | None = None,
) -> CompetitionResult:
    """Issue claims for one geometry under the dominance rule."""
    scores = scores if scores is not None else score_geometry(geometry, terms)
    if geometry.closure_closed and scores:
        leader = max(scores.values(), key=lambda s: s.total)
        trail = leader.evidence + (
            ClaimEvidence("closure", "grid closes", CORROBORATION_POINTS),
        )
        scores = dict(scores)
        scores[leader.family] = FamilyScore(
            leader.family,
            leader.total + CORROBORATION_POINTS,
            dict(leader.by_channel),
            trail,
        )
    ranked = sorted(scores.values(), key=lambda s: -s.total)
    claims: list[str] = []
    contested: list[str] = []
    explained_all: dict[str, float] = {}
    for candidate in ranked:
        if candidate.total < CLAIM_FLOOR:
            continue
        foreign, explained = _explained_foreign(candidate.family, scores, edges)
        explained_all.update(explained)
        if foreign <= FOREIGN_ALLOWANCE:
            claims.append(candidate.family)
        elif candidate.total >= DOMINANCE_RATIO * foreign:
            claims.append(candidate.family)
    if not claims:
        floored = [c.family for c in ranked if c.total >= CLAIM_FLOOR]
        if len(floored) >= 2:
            top, second = scores[floored[0]].total, scores[floored[1]].total
            if top < DOMINANCE_RATIO * second:
                claims = floored[:2]
                contested = floored[:2]
    if len(claims) >= 2:
        top = scores[claims[0]].total
        second = scores[claims[1]].total
        if top < DOMINANCE_RATIO * second:
            contested = claims[:2]
    return CompetitionResult(
        claims=tuple(claims),
        contested=tuple(contested),
        scores=scores,
        foreign_explained=explained_all,
    )


def compete_filing(
    geometries: list[GeometryText] | tuple[GeometryText, ...],
    terms: tuple[SignatureTerm, ...] = SIGNATURE_TERMS,
    edges: tuple[ContainmentEdge, ...] = CONTAINMENT_EDGES,
) -> list[CompetitionResult]:
    """Compete one filing's geometries with context fed back.

    Header inheritance: a fragment with no claim inherits discounted
    evidence from the nearest preceding claimed geometry in the same
    note or section. Cross-parse ties: an unclaimed geometry sharing
    a note title with two or more same-family claims gains tie
    evidence for that family. Neither act overrides a scored claim.
    """
    results = [compete(g, terms, edges) for g in geometries]
    claimed_by_title: dict[str, dict[str, int]] = {}
    for geometry, result in zip(geometries, results, strict=True):
        if geometry.note_title and result.claims:
            bucket = claimed_by_title.setdefault(geometry.note_title, {})
            for family in result.claims:
                bucket[family] = bucket.get(family, 0) + 1
    for index, (geometry, result) in enumerate(zip(geometries, results, strict=True)):
        if result.claims:
            continue
        bonus: dict[str, float] = {}
        if geometry.is_fragment:
            for back in range(1, INHERITANCE_MAX_DISTANCE + 1):
                prior_index = index - back
                if prior_index < 0:
                    break
                prior = geometries[prior_index]
                prior_result = results[prior_index]
                if not prior_result.claims:
                    continue
                same_home = (
                    (
                        prior.note_title is not None
                        and prior.note_title == geometry.note_title
                    )
                    or (
                        prior.section_item is not None
                        and prior.section_item == geometry.section_item
                    )
                    or back == 1
                )
                if not same_home:
                    continue
                for family in prior_result.claims:
                    inherited = INHERITANCE_FACTOR * prior_result.scores[family].total
                    bonus[family] = max(bonus.get(family, 0.0), inherited)
                break
        if geometry.note_title:
            for family, count in claimed_by_title.get(geometry.note_title, {}).items():
                if count >= 2:
                    bonus[family] = bonus.get(family, 0.0) + TIE_POINTS
        if not bonus:
            continue
        adjusted: dict[str, FamilyScore] = {}
        for family, score in result.scores.items():
            add = bonus.pop(family, 0.0)
            if add:
                trail = score.evidence + (
                    ClaimEvidence("context", "inherited/tie evidence", add),
                )
                channels = dict(score.by_channel)
                channels["context"] = channels.get("context", 0.0) + add
                adjusted[family] = FamilyScore(
                    family, score.total + add, channels, trail
                )
            else:
                adjusted[family] = score
        for family, add in bonus.items():
            adjusted[family] = FamilyScore(
                family,
                add,
                {"context": add},
                (ClaimEvidence("context", "inherited/tie evidence", add),),
            )
        results[index] = compete(geometries[index], terms, edges, scores=adjusted)
    return results
