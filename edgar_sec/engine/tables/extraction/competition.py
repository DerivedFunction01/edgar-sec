"""Signature competition: scored claiming over signature profiles.

A claim issues only when a family's own profile dominates the
geometry's text and the foreign profile mass is negligible or
explained by a measured containment edge. Closure corroborates.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from edgar_sec.engine.tables.extraction.admission_evidence import apply_admissions
from edgar_sec.engine.tables.extraction.aoci_gate import aoci_gate_detail
from edgar_sec.engine.tables.extraction.derivatives_evidence import (
    DerivativesText,
    _term_pattern,
    derivatives_subject_for_geometry,
    evaluate_derivatives_evidence,
)
from edgar_sec.engine.tables.extraction.genre_seat import (
    apply_section_refusals,
    geometry_refusal,
)
from edgar_sec.engine.tables.extraction.section_gate import ScopeRow
from edgar_sec.engine.tables.extraction.form_tests import (
    FormTestOutcome,
    evaluate_form_tests,
)
from edgar_sec.engine.tables.extraction.form_test_specs import (
    DERIVATIVES_EVIDENCE_SPECS,
)
from edgar_sec.engine.tables.extraction.pension_evidence import (
    PENSION_ANCHOR_SPECS,
    PensionText,
    evaluate_pension_anchor,
)
from edgar_sec.engine.tables.extraction.summary_separator import (
    SummarySeparatorResult,
    evaluate_summary_separator,
)
from edgar_sec.engine.tables.extraction.leadin_segmentation import (
    lead_title_text,
    leadin_segment,
)
from edgar_sec.engine.tables.extraction.detail_signatures import (
    SCORED_VETOES,
    detail_signatures,
)
from edgar_sec.engine.tables.extraction.normalize import normalize_text
from edgar_sec.engine.tables.extraction.term_vetoes import (
    lead_channel_text,
    term_veto_hits,
)
from edgar_sec.engine.tables.toc.patterns import RE_NOTE_HEADING_CUE
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

# Calibration constants, derivation-priced by the calibration
# harness over the adjudicated corpora; the pin iteration
# re-prices them against the 1B map profile.
CLAIM_FLOOR = 5.0
DOMINANCE_RATIO = 1.25
FOREIGN_ALLOWANCE = 0.25
CORROBORATION_POINTS = 0.75
INHERITANCE_FACTOR = 0.5
INHERITANCE_MAX_DISTANCE = 3
TIE_POINTS = 1.0
FRAGMENT_MAX_STUBS = 8

# False-claim constants, derivation-priced. Vetoes are
# scored negative evidence only — the
# Deliverable 1 pricing earned no hard veto anywhere.
VETO_POINTS = 1.5
LADDER_MARGIN = 1.0
LADDER_SINGLE_MODE = "contest"
REACH_DOMINANCE = 1.25
REACH_FLOORS = {"pension": 4.0, "deferred_tax": 4.0}
REACH_MIN_STUB_SHARE: dict[str, float] = {
    "pension": 0.5,
    "deferred_tax": 0.5,
}

_HEADING_NUMBERED = re.compile(r"^\d+\.\s+\S")


def heading_text(prose_before: str, prose_after: str, caption: str) -> str:
    """Heading lines framing a geometry: note headings and titles."""
    lines: list[str] = []
    for source in (prose_before or "", prose_after or ""):
        for line in source.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if RE_NOTE_HEADING_CUE.search(stripped) or _HEADING_NUMBERED.match(
                stripped
            ):
                if len(stripped) < 120:
                    lines.append(stripped)
            elif len(stripped) >= 8 and stripped == stripped.upper():
                if any(ch.isalpha() for ch in stripped):
                    lines.append(stripped)
    lines.append(caption or "")
    return normalize_text(" ".join(lines))


@dataclass(frozen=True, slots=True)
class GeometryText:
    """One geometry's text evidence, by channel, plus context."""

    caption: str = ""
    leadin: str = ""
    notehead: str = ""
    lead_title: str = ""
    lead: str = ""
    prose_after: str = ""
    stubs: tuple[str, ...] = ()
    closure_closed: bool | None = None
    note_title: str | None = None
    section_item: str | None = None
    form_tests: tuple[FormTestOutcome, ...] = ()
    summary_separator: SummarySeparatorResult | None = None
    grid_text: str = ""
    headers: tuple[str, ...] = ()
    in_toc_span: bool = False
    in_closing_span: bool = False
    closing_kind: str | None = None
    front_matter: bool = False
    note_seated: bool = False
    numeric_cells: int = 0
    data_rows: int = 0
    grid_rows: int = 0
    max_row_cells: int = 0
    index_named_share: float = 0.0
    page_ref_share: float = 0.0
    page_ref_only: bool = False
    exhibit_stub_share: float = 0.0
    section_form: str | None = None
    section_part: str | None = None
    section_title: str | None = None

    @property
    def stub_text(self) -> str:
        """The stub distribution as one normalized skeleton text."""
        return normalize_text(" ".join(self.stubs))

    @property
    def is_fragment(self) -> bool:
        """A fragment: few stubs and no caption of its own."""
        return len(self.stubs) <= FRAGMENT_MAX_STUBS and not self.caption.strip()


def geometry_text_from_table(table, *, evaluate_stage: bool = True) -> GeometryText:
    """Build channel text from a TypedTable (duck-typed context)."""
    context = table.context
    caption = " | ".join(list(context.caption_stack) + list(table.caption.titles))
    stubs = tuple(row.label for row in table.rows if row.label)
    note = context.note
    section = context.section
    grid_text = normalize_text(
        " ".join(cell for row in context.rows for cell in row if cell.strip())
    )
    consumed = table.caption.consumed_rows
    first_data = next(
        (i for i, row in enumerate(table.rows) if row.kind.name == "DATA"),
        len(table.rows),
    )
    zone = max(consumed + table.header_rows, consumed + first_data)
    headers = tuple(cell for row in context.rows[:zone] for cell in row if cell.strip())
    return GeometryText(
        caption=caption,
        lead=lead_channel_text(caption, context.prose_before or ""),
        leadin=leadin_segment(context.prose_before or ""),
        notehead=heading_text(
            context.prose_before or "", context.prose_after or "", caption
        ),
        lead_title=lead_title_text(context.prose_before or ""),
        prose_after=context.prose_after or "",
        stubs=stubs,
        note_title=note.title if note else None,
        section_item=section.item if section else None,
        form_tests=evaluate_form_tests(table) if evaluate_stage else (),
        summary_separator=(
            evaluate_summary_separator(table) if evaluate_stage else None
        ),
        grid_text=grid_text,
        headers=headers,
        in_toc_span=context.in_toc_span,
        in_closing_span=context.in_closing_span,
        closing_kind=context.closing_kind,
        front_matter=context.front_matter,
        note_seated=note is not None,
        numeric_cells=context.numeric_cells,
        data_rows=context.data_rows,
        grid_rows=context.grid_rows,
        max_row_cells=context.max_row_cells,
        index_named_share=context.index_named_share,
        page_ref_share=context.page_ref_share,
        page_ref_only=context.page_ref_only,
        exhibit_stub_share=context.exhibit_stub_share,
        section_form=section.form if section else None,
        section_part=section.part if section else None,
        section_title=section.title if section else None,
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
    scopes: tuple[ScopeRow, ...] = (),
) -> CompetitionResult:
    """Issue claims for one geometry under the dominance rule."""
    if geometry_refusal(geometry) is not None:
        return CompetitionResult(claims=(), contested=(), scores={})
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
    # Term vetoes, hard tier (Step 6 v2 re-price; owner imposter
    # ruling): a hit removes the family's claim outright. The
    # score stays as foreign mass and carries the veto in its
    # trail; the family is barred from claims, contested pairs,
    # and reach below, and compete_filing re-applies this on
    # every re-compete, so inheritance cannot resurrect it.
    veto_hits = term_veto_hits(geometry)
    hard_vetoed = {
        family: tiers["hard"] for family, tiers in veto_hits.items() if "hard" in tiers
    }
    if hard_vetoed:
        scores = dict(scores)
        for family, term in hard_vetoed.items():
            score = scores.get(family)
            if score is None:
                continue
            scores[family] = FamilyScore(
                family,
                score.total,
                dict(score.by_channel),
                score.evidence + (ClaimEvidence("veto", f"hard:{term}", 0.0),),
            )
    ranked = sorted(scores.values(), key=lambda s: -s.total)
    claims: list[str] = []
    contested: list[str] = []
    explained_all: dict[str, float] = {}
    explained_by: dict[str, dict[str, float]] = {}
    for candidate in ranked:
        if candidate.family in hard_vetoed:
            continue
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
        floored = [
            c.family
            for c in ranked
            if c.total >= CLAIM_FLOOR and c.family not in hard_vetoed
        ]
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
    # Cure 1 + Step 9 AOCI gates: the verdict is aoci_gate's.
    aoci_detail = aoci_gate_detail(claims, scores, geometry)
    if aoci_detail is not None:
        claims.remove("aoci_rollforward")
        if "aoci_rollforward" in contested:
            contested.remove("aoci_rollforward")
        gated = scores["aoci_rollforward"]
        scores = dict(scores)
        scores["aoci_rollforward"] = FamilyScore(
            gated.family,
            gated.total,
            dict(gated.by_channel),
            gated.evidence + (ClaimEvidence("gate", aoci_detail, 0.0),),
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
    # Cure 6 (derivatives gate): a derivatives claim requires U/A
    # evidence in the geometry itself; the gate is registry data
    # (form_test_specs.DERIVATIVES_EVIDENCE_SPECS), priced on the
    # The measured evidence-class split: no-evidence claims are the
    # false mass.
    deriv_spec = DERIVATIVES_EVIDENCE_SPECS.get("derivatives_hedging")
    deriv_evidence = (
        evaluate_derivatives_evidence(
            DerivativesText.from_geometry(geometry), deriv_spec
        )
        if deriv_spec is not None
        else None
    )
    if (
        deriv_evidence is not None
        and not deriv_evidence.admitted
        and "derivatives_hedging" in claims
    ):
        claims.remove("derivatives_hedging")
        if "derivatives_hedging" in contested:
            contested.remove("derivatives_hedging")
        gated = scores["derivatives_hedging"]
        scores = dict(scores)
        scores["derivatives_hedging"] = FamilyScore(
            gated.family,
            gated.total,
            dict(gated.by_channel),
            gated.evidence
            + (ClaimEvidence("gate", f"derivatives: {deriv_evidence.detail}", 0.0),),
        )
    # Cure 7 (derivatives subject gate): a derivatives claim also
    # requires the rank-1 subject verdict — derivative evidence in
    # the geometry's own framing, not only its body content.
    deriv_subject = (
        derivatives_subject_for_geometry(geometry) if deriv_spec is not None else None
    )
    if (
        deriv_subject is not None
        and not deriv_subject.subject
        and "derivatives_hedging" in claims
    ):
        claims.remove("derivatives_hedging")
        if "derivatives_hedging" in contested:
            contested.remove("derivatives_hedging")
        gated = scores["derivatives_hedging"]
        scores = dict(scores)
        scores["derivatives_hedging"] = FamilyScore(
            gated.family,
            gated.total,
            dict(gated.by_channel),
            gated.evidence
            + (
                ClaimEvidence(
                    "gate", f"derivatives subject: {deriv_subject.detail}", 0.0
                ),
            ),
        )
    # Cures 4+5 (claim-reach): subject-evidence presence claims
    # an otherwise unclaimed geometry at declared provenance.
    reach: list[str] = []
    if not claims:
        best_other = max(
            (s.total for f, s in scores.items() if f not in REACH_FLOORS),
            default=0.0,
        )
        for family, floor in REACH_FLOORS.items():
            if family in hard_vetoed:
                continue
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
        # Derivatives reach: strong U/A evidence (a subject-named
        # instrument, a period listing, an A-frontier form) claims
        # an otherwise unclaimed geometry whose signature score
        # alone stays under the floor — the plain-listing misses.
        if (
            not claims
            and "derivatives_hedging" not in hard_vetoed
            and deriv_evidence is not None
            and deriv_evidence.admitted
            and deriv_evidence.strong
            and deriv_subject is not None
            and deriv_subject.subject
        ):
            existing = scores.get("derivatives_hedging")
            if existing is None:
                scores = dict(scores)
                scores["derivatives_hedging"] = FamilyScore(
                    "derivatives_hedging",
                    CLAIM_FLOOR,
                    {"gate": CLAIM_FLOOR},
                    (ClaimEvidence("gate", deriv_evidence.detail, CLAIM_FLOOR),),
                )
            elif existing.total < CLAIM_FLOOR:
                lift = CLAIM_FLOOR - existing.total
                channels = dict(existing.by_channel)
                channels["gate"] = channels.get("gate", 0.0) + lift
                scores = dict(scores)
                scores["derivatives_hedging"] = FamilyScore(
                    existing.family,
                    CLAIM_FLOOR,
                    channels,
                    existing.evidence
                    + (ClaimEvidence("gate", deriv_evidence.detail, lift),),
                )
            claims.append("derivatives_hedging")
            reach.append("derivatives_hedging")
    # Step 7 admission (priced): the core-signal reads seat
    # claims the signature competition cannot reach.
    admission, scores = apply_admissions(
        geometry.form_tests,
        claims,
        scores,
        hard_vetoed,
        floor=CLAIM_FLOOR,
        score_type=FamilyScore,
        evidence_type=ClaimEvidence,
    )
    # Pension core-anchor gate: a pension claim requires a
    # disjunctive ASC 715 core anchor on the geometry's own
    # surfaces, its following prose completing each leg's surface.
    pension_spec = PENSION_ANCHOR_SPECS.get("pension")
    if pension_spec is not None and "pension" in claims:
        pension_evidence = evaluate_pension_anchor(
            PensionText.from_geometry(geometry), pension_spec
        )
        if not pension_evidence.admitted:
            claims.remove("pension")
            if "pension" in contested:
                contested.remove("pension")
            gated = scores["pension"]
            scores = dict(scores)
            scores["pension"] = FamilyScore(
                gated.family,
                gated.total,
                dict(gated.by_channel),
                gated.evidence
                + (ClaimEvidence("gate", f"pension: {pension_evidence.detail}", 0.0),),
            )
    if scopes:
        kept, kept_contested = apply_section_refusals(
            claims, contested, geometry, scopes
        )
        claims, contested = kept, kept_contested
    # S1 separator gate: a fired statement-summary rule denies
    # every claim — the priced mass is a composition (a summary
    # of a statement), claimed by no family (S1 pricing covers).
    separator = geometry.summary_separator
    if separator is not None and separator.fired and claims:
        removed, claims, contested = tuple(claims), [], []
        reach = [family for family in reach if family not in removed]
        scores = dict(scores)
        for family in removed:
            gated = scores[family]
            scores[family] = FamilyScore(
                gated.family,
                gated.total,
                dict(gated.by_channel),
                gated.evidence
                + (
                    ClaimEvidence(
                        "gate", f"summary separator: {separator.detail}", 0.0
                    ),
                ),
            )
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
            else "admission"
            if family in admission
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
    scopes: tuple[ScopeRow, ...] = (),
) -> list[CompetitionResult]:
    """Compete one filing's geometries with context fed back.

    Context lends evidence to unclaimed geometries only; it never
    overrides a geometry's own scored claim.
    """
    results = [
        compete(g, terms, edges, ladder_terms=ladder_terms, scopes=scopes)
        for g in geometries
    ]
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
            scopes=scopes,
        )
    return results
