"""Signature competition: scored claiming over signature profiles.

A claim issues only when a family's own profile dominates the
geometry's text and the foreign profile mass is negligible or
explained by a measured containment edge. Closure corroborates.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from functools import lru_cache

from edgar_sec.engine.tables.extraction.form_tests import (
    FormTestOutcome,
    evaluate_form_tests,
)
from edgar_sec.engine.tables.extraction.normalize import normalize_text
from edgar_sec.engine.tables.extraction.signature_profiles import (
    CHANNEL_WEIGHTS,
    CONTAINMENT_EDGES,
    INHERITANCE_FACTORS,
    LADDER_EDGE_TERMS,
    SIGNATURE_TERMS,
    ContainmentEdge,
    LadderTerm,
    SignatureTerm,
)

# Calibration constants, derivation-priced by the Step 1 harness
# over the adjudicated corpora (record: improvement Step 1; the
# pin iteration re-prices them against the 1B map profile).
CLAIM_FLOOR = 5.0
DOMINANCE_RATIO = 1.25
FOREIGN_ALLOWANCE = 0.25
CORROBORATION_POINTS = 0.75
INHERITANCE_FACTOR = 0.5
INHERITANCE_MAX_DISTANCE = 3
TIE_POINTS = 1.0
FRAGMENT_MAX_STUBS = 8

# Step 2A constants, derivation-priced (record: improvement
# Step 2A). Vetoes are scored negative evidence only — the
# Deliverable 1 pricing earned no hard veto anywhere.
VETO_POINTS = 1.5
AOCI_STUB_EVIDENCE_MIN = 6.0
AOCI_GATE_MODE = "seat"
LADDER_MARGIN = 1.0
LADDER_SINGLE_MODE = "contest"
REACH_DOMINANCE = 1.25
REACH_FLOORS = {"pension": 4.0, "deferred_tax": 4.0}
REACH_MIN_STUB_SHARE: dict[str, float] = {
    "pension": 0.5,
    "deferred_tax": 0.5,
}

# Detail signatures: named detail shapes a summary family never
# carries, matched over stub + caption text (Deliverable 1 sets).
DETAIL_SIGNATURES: dict[str, tuple[str, ...]] = {
    "maturity_buckets": (
        "thereafter",
        "less than 1 year",
        "1 to 2 years",
        "2 to 3 years",
        "3 to 4 years",
        "4 to 5 years",
        "more than 5 years",
        "fiscal year ending",
        "years ending december",
    ),
    "rollforward_movement": (
        "beginning balance",
        "beginning of year",
        "beginning of period",
        "ending balance",
        "end of year",
        "end of period",
        "additions",
        "deductions",
        "settlements",
        "curtailments",
    ),
    "period_columns": (
        "three months ended",
        "six months ended",
        "nine months ended",
        "year ended",
        "years ended",
        "quarter ended",
    ),
    "supplemental_schedule": (
        "supplemental",
        "schedule of",
        "noncash",
        "non-cash",
    ),
    "grant_activity": (
        "granted",
        "exercised",
        "forfeited",
        "vested",
        "unvested",
        "shares authorized",
        "options outstanding",
        "shares available",
    ),
    "composition_detail": (
        "valuation allowance",
        "net deferred tax",
        "gross deferred tax",
        "tax effect of",
        "deferred tax assets",
        "deferred tax liabilities",
    ),
    "percentage_rows": (
        "% of",
        "percentage of",
        "percent of",
        "as a percentage",
    ),
    "segment_detail": (
        "total segment",
        "corporate and other",
        "eliminations",
        "segment profit",
        "segment revenue",
        "operating segments",
    ),
    "acquisition_detail": (
        "purchase price",
        "consideration transferred",
        "identifiable assets acquired",
        "goodwill recognized",
        "acquisition date",
    ),
}
_YEAR_TOKENS = ("2022", "2023", "2024", "2025", "2026", "2027")

# The scored class of the Deliverable 1 veto pricing: family ->
# signatures whose kill rate beat member collateral by the rule.
SCORED_VETOES: dict[str, tuple[str, ...]] = {
    "balance_sheet": (
        "acquisition_detail",
        "period_columns",
        "rollforward_movement",
    ),
    "comprehensive_income": ("year_columns",),
    "deferred_tax": ("period_columns",),
    "equity_statement": ("composition_detail",),
    "income_statement": ("rollforward_movement", "segment_detail"),
    "intangibles": (
        "maturity_buckets",
        "percentage_rows",
        "period_columns",
        "year_columns",
    ),
    "stock_comp_rollforward": ("period_columns",),
}

_HEADING_NOTE = re.compile(r"notes to|^\s*note\s+\d", re.IGNORECASE)
_HEADING_NUMBERED = re.compile(r"^\d+\.\s+\S")
_TITLE_SPLIT = re.compile(r"\s*\|\s*|\n")


@lru_cache(maxsize=None)
def _term_pattern(term: str) -> re.Pattern[str]:
    """One term's word-boundary pattern, compiled once per term."""
    return re.compile(r"\b" + re.escape(term) + r"\b")


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
    return normalize_text(" ".join(lines))


def lead_title_text(prose_before: str) -> str:
    """The lead-in's title segments: its first two framing chunks."""
    segments = []
    for chunk in _TITLE_SPLIT.split(prose_before or ""):
        stripped = chunk.strip()
        if stripped:
            segments.append(stripped)
        if len(segments) >= 3:
            break
    return " ".join(segments[:2])


@dataclass(frozen=True, slots=True)
class GeometryText:
    """One geometry's text evidence, by channel, plus context."""

    caption: str = ""
    leadin: str = ""
    notehead: str = ""
    lead_title: str = ""
    stubs: tuple[str, ...] = ()
    closure_closed: bool | None = None
    note_title: str | None = None
    section_item: str | None = None
    form_tests: tuple[FormTestOutcome, ...] = ()

    @property
    def stub_text(self) -> str:
        """The stub distribution as one normalized skeleton text."""
        return normalize_text(" ".join(self.stubs))

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
        lead_title=lead_title_text(context.prose_before or ""),
        stubs=stubs,
        note_title=note.title if note else None,
        section_item=section.item if section else None,
        form_tests=evaluate_form_tests(table),
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


def _term_present(term: str, text: str) -> bool:
    if " " in term or "-" in term:
        return term in text
    return _term_pattern(term).search(text) is not None


def detail_signatures(geometry: GeometryText) -> set[str]:
    """The named detail signatures present in stub + caption text."""
    text = geometry.stub_text + " " + normalize_text(geometry.caption)
    found = {
        name
        for name, terms in DETAIL_SIGNATURES.items()
        if any(term in text for term in terms)
    }
    years = {y for y in _YEAR_TOKENS if y in geometry.stub_text}
    if len(years) >= 2:
        found.add("year_columns")
    return found


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


def _aoci_rollforward_evidence(score: FamilyScore) -> bool:
    """Rollforward evidence: framing mass, or a movement-shaped stub."""
    framing = sum(
        score.by_channel.get(c, 0.0) for c in ("caption", "notehead", "lead_title")
    )
    return framing > 0 or score.by_channel.get("stub", 0.0) >= (AOCI_STUB_EVIDENCE_MIN)


def _ladder_direction(
    geometry: GeometryText,
    ladder_terms: tuple[LadderTerm, ...],
) -> float:
    """Signed debt/lease evidence: positive leans lease, from the edge."""
    text = geometry.stub_text + " " + normalize_text(geometry.caption)
    direction = 0.0
    for spec in ladder_terms:
        if spec.term in text:
            direction += math.log(
                (spec.support_lease + 1.0) / (spec.support_debt + 1.0)
            )
    return direction


def compete(
    geometry: GeometryText,
    terms: tuple[SignatureTerm, ...] = SIGNATURE_TERMS,
    edges: tuple[ContainmentEdge, ...] = CONTAINMENT_EDGES,
    scores: dict[str, FamilyScore] | None = None,
    ladder_terms: tuple[LadderTerm, ...] = LADDER_EDGE_TERMS,
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
    explained_by: dict[str, dict[str, float]] = {}
    for candidate in ranked:
        if candidate.total < CLAIM_FLOOR:
            continue
        foreign, explained = _explained_foreign(candidate.family, scores, edges)
        explained_all.update(explained)
        explained_by[candidate.family] = explained
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
    # Cure 1 (aoci bleed): an equity-seated aoci claim without
    # rollforward evidence spawns from its column alone — gated.
    aoci_seated = AOCI_GATE_MODE == "any" or (
        AOCI_GATE_MODE == "seat" and "equity_statement" in claims
    )
    if (
        aoci_seated
        and "aoci_rollforward" in claims
        and not _aoci_rollforward_evidence(scores["aoci_rollforward"])
    ):
        claims.remove("aoci_rollforward")
        if "aoci_rollforward" in contested:
            contested.remove("aoci_rollforward")
        gated = scores["aoci_rollforward"]
        scores = dict(scores)
        scores["aoci_rollforward"] = FamilyScore(
            gated.family,
            gated.total,
            dict(gated.by_channel),
            gated.evidence
            + (ClaimEvidence("gate", "aoci: no rollforward evidence", 0.0),),
        )
    # Cure 2 (ladder attribution): the map's priced edge terms
    # decide debt vs lease before the pair stays contested.
    attributed: list[str] = []
    if "debt_maturity" in claims and "lease_maturity" in claims:
        direction = _ladder_direction(geometry, ladder_terms)
        loser = None
        if direction >= LADDER_MARGIN:
            loser = "debt_maturity"
        elif direction <= -LADDER_MARGIN:
            loser = "lease_maturity"
        if loser is not None:
            claims.remove(loser)
            attributed.append(loser)
            if loser in contested:
                contested.remove(loser)
            if len(contested) < 2:
                contested = []
    # Cure 2, single-claim arm: a decisive edge direction against
    # a lone ladder claim contests or flips it (priced arms).
    if LADDER_SINGLE_MODE != "off":
        ladder_claims = [f for f in claims if f in ("debt_maturity", "lease_maturity")]
        if len(ladder_claims) == 1:
            holder = ladder_claims[0]
            other = "lease_maturity" if holder == "debt_maturity" else "debt_maturity"
            direction = _ladder_direction(geometry, ladder_terms)
            opposed = (
                direction >= LADDER_MARGIN
                if holder == "debt_maturity"
                else direction <= -LADDER_MARGIN
            )
            if opposed and other in scores:
                if LADDER_SINGLE_MODE == "flip":
                    claims.remove(holder)
                    claims.append(other)
                    attributed.append(holder)
                elif not contested:
                    claims.append(other)
                    contested = [holder, other]
    # Cures 4+5 (claim-reach): subject-evidence presence claims
    # an otherwise unclaimed geometry at declared provenance.
    reach: list[str] = []
    if not claims:
        best_other = max(
            (s.total for f, s in scores.items() if f not in REACH_FLOORS),
            default=0.0,
        )
        for family, floor in REACH_FLOORS.items():
            score = scores.get(family)
            if score is None:
                continue
            stub_share = (
                score.by_channel.get("stub", 0.0) / score.total
                if score.total > 0
                else 0.0
            )
            if stub_share < REACH_MIN_STUB_SHARE.get(family, 0.0):
                continue
            if score.total >= floor and score.total >= (REACH_DOMINANCE * best_other):
                claims.append(family)
                reach.append(family)
    role = (
        "continuation"
        if geometry.is_fragment
        else "head"
        if geometry.caption.strip()
        else "standalone"
    )
    grouped: list[ClaimGroup] = []
    for family in claims:
        score = scores[family]
        state = (
            "contested"
            if family in contested
            else "reach"
            if family in reach
            else "claimed"
        )
        grouped.append(
            ClaimGroup(
                family,
                score.total,
                state,
                role,
                dict(score.by_channel),
                tuple(e.detail for e in score.evidence if e.channel == "veto"),
                sum(explained_by.get(family, {}).values()),
            )
        )
    for family in attributed:
        score = scores[family]
        grouped.append(
            ClaimGroup(
                family,
                score.total,
                "attributed",
                role,
                dict(score.by_channel),
                tuple(e.detail for e in score.evidence if e.channel == "veto"),
                sum(explained_by.get(family, {}).values()),
            )
        )
    return CompetitionResult(
        claims=tuple(claims),
        contested=tuple(contested),
        scores=scores,
        foreign_explained=explained_all,
        groups=tuple(grouped),
    )


# Inheritance lends a fragment the discounted evidence of the
# nearest preceding claim in its note or section; a note title
# shared with 2+ same-family claims lends that family tie evidence.
def compete_filing(
    geometries: list[GeometryText] | tuple[GeometryText, ...],
    terms: tuple[SignatureTerm, ...] = SIGNATURE_TERMS,
    edges: tuple[ContainmentEdge, ...] = CONTAINMENT_EDGES,
    ladder_terms: tuple[LadderTerm, ...] = LADDER_EDGE_TERMS,
) -> list[CompetitionResult]:
    """Compete one filing's geometries with context fed back.

    Context lends evidence to unclaimed geometries only; it never
    overrides a geometry's own scored claim.
    """
    results = [compete(g, terms, edges, ladder_terms=ladder_terms) for g in geometries]
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
                    factor = INHERITANCE_FACTORS.get(family, INHERITANCE_FACTOR)
                    inherited = factor * prior_result.scores[family].total
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
        results[index] = compete(
            geometries[index],
            terms,
            edges,
            scores=adjusted,
            ladder_terms=ladder_terms,
        )
    return results
