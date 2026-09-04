"""Multi-zone BoW classifier for table families."""

from __future__ import annotations

from typing import TYPE_CHECKING

from defs.taxonomy.tables.families import FAMILY_SPECS
from defs.taxonomy.tables.shapes import validate_shape
from defs.taxonomy.tables.specs import (
    FamilyClassification,
    FamilyMatch,
    RepairPolicy,
    TableFamilySpec,
    VocabularyEvidence,
)

if TYPE_CHECKING:
    from defs.sec_forms.context import SectionContext
from defs.text.bow import (
    BowScore,
    EvidenceContext,
    score_tokens,
    tokenize,
)

_COVER_FAMILIES: tuple[str, ...] = (
    "cover_layout",
    "checkbox_grid",
    "registration_table",
)


def _bow_to_evidence(score: BowScore, zone: str) -> VocabularyEvidence:
    """Translate a BowScore into a typed VocabularyEvidence."""
    pos_hits: list[str] = []
    supp_hits: list[str] = []
    for hit in score.hits:
        if "support" in hit.tier or "qualifier" in hit.tier:
            supp_hits.append(hit.term)
        else:
            pos_hits.append(hit.term)

    return VocabularyEvidence(
        zone=zone,
        positive_hits=tuple(pos_hits),
        supporting_hits=tuple(supp_hits),
        refuting_hits=score.exclusions,
        score=float(score.score),
        vocabulary_version="1.0",
    )


def classify_table(
    grid: list[list[str]],
    *,
    section_context: SectionContext | None = None,
    candidate_families: tuple[str, ...] | None = None,
) -> FamilyClassification:
    """Classify a 2D table grid against registered table families.

    Zones evaluated:
    - ``header``: Table rows 0..min(2, len(grid))
    - ``body``: Remaining table rows
    - ``neighbor``: Immediate preceding blocks from section context
    - ``section``: Section heading from section context
    """
    if not grid:
        return FamilyClassification(
            family=None,
            confidence=0.0,
            repair_policy=RepairPolicy.NO_REPAIR,
        )

    # 1. Zone text extraction
    header_rows = grid[: min(2, len(grid))]
    body_rows = grid[min(2, len(grid)) :]
    header_text = " ".join(c for r in header_rows for c in r if c.strip())
    body_text = " ".join(c for r in body_rows for c in r if c.strip())

    neighbor_text = ""
    section_text = ""
    in_cover_scope = False
    if section_context is not None:
        if section_context.preceding_blocks:
            neighbor_text = " ".join(section_context.preceding_blocks)
        if section_context.heading:
            section_text = section_context.heading
        if section_context.cover_scope is not None:
            in_cover_scope = section_context.cover_scope.active

    # 2. Candidate family filtering
    families_to_evaluate: tuple[str, ...]
    if candidate_families is not None:
        families_to_evaluate = candidate_families
    elif in_cover_scope:
        families_to_evaluate = _COVER_FAMILIES
    else:
        families_to_evaluate = tuple(FAMILY_SPECS.keys())

    header_tokens = tokenize(header_text)
    body_tokens = tokenize(body_text)
    neighbor_tokens = tokenize(neighbor_text) if neighbor_text else []
    section_tokens = tokenize(section_text) if section_text else []
    ctx = EvidenceContext(min_words=1)

    candidates: list[tuple[FamilyMatch, RepairPolicy]] = []

    # 3. Evaluate each family
    for name in families_to_evaluate:
        spec: TableFamilySpec | None = FAMILY_SPECS.get(name)
        if spec is None:
            continue

        h_score = score_tokens(header_tokens, spec.evidence_pack, ctx)
        b_score = score_tokens(body_tokens, spec.evidence_pack, ctx)
        n_score = (
            score_tokens(neighbor_tokens, spec.evidence_pack, ctx)
            if neighbor_tokens
            else None
        )
        s_score = (
            score_tokens(section_tokens, spec.evidence_pack, ctx)
            if section_tokens
            else None
        )

        # Exclusions in any zone veto the family immediately
        if h_score.exclusions or b_score.exclusions:
            continue
        if n_score is not None and n_score.exclusions:
            continue

        # Intrinsic table score
        table_score = max(h_score.score, b_score.score)
        confidence = max(h_score.confidence, b_score.confidence)

        # Context boosting for ambiguous intrinsic score
        if table_score == 1 and (
            (n_score and n_score.score >= 1)
            or (s_score and s_score.score >= 1)
            or in_cover_scope
        ):
            table_score = 2
            confidence = max(confidence, 0.65)

        if table_score < 2:
            continue

        # Validate geometric shape
        shape_ok, _ = validate_shape(grid, spec.shape, in_scope=in_cover_scope)
        if not shape_ok:
            continue

        # Found confirmed match
        evidence_list = [
            _bow_to_evidence(h_score, "header"),
            _bow_to_evidence(b_score, "body"),
        ]
        if n_score:
            evidence_list.append(_bow_to_evidence(n_score, "neighbor"))
        if s_score:
            evidence_list.append(_bow_to_evidence(s_score, "section"))

        match = FamilyMatch(
            family=spec.name,
            confidence=confidence,
            score=table_score,
            evidence=tuple(evidence_list),
            structural_confirmed=True,
            priority=spec.priority,
        )
        candidates.append((match, spec.repair_policy))

    if not candidates:
        return FamilyClassification(
            family=None,
            confidence=0.0,
            repair_policy=RepairPolicy.NO_REPAIR,
        )

    # Sort candidates by priority descending, confidence descending, then score descending
    candidates.sort(
        key=lambda item: (item[0].priority, item[0].confidence, item[0].score),
        reverse=True,
    )
    primary_match, primary_policy = candidates[0]
    secondary_tags = tuple(item[0].family for item in candidates[1:])

    return FamilyClassification(
        family=primary_match.family,
        confidence=primary_match.confidence,
        evidence=primary_match.evidence,
        structural_confirmed=primary_match.structural_confirmed,
        repair_policy=primary_policy,
        tags=secondary_tags,
        all_matches=tuple(item[0] for item in candidates),
    )
