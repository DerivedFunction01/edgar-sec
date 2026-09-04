"""Base specification classes, evidence models, and tier builder helpers for table families."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from defs.tables.templates.scope import TableScope
from defs.taxonomy.tables.shapes import ShapeConstraint
from defs.text.bow import CompiledEvidencePack, EvidenceTier, tokenize


class RepairPolicy(str, Enum):
    """Repair authorization level for a table-family classification."""

    NO_REPAIR = "no_repair"
    PRESENTATION_ONLY = "presentation_only"
    SAFE_GRID_REPAIR = "safe_grid_repair"
    FAMILY_TEMPLATE = "family_template"
    REVIEW_REQUIRED = "review_required"


@dataclass(frozen=True, slots=True)
class VocabularyEvidence:
    """Per-zone vocabulary evidence for a single classification zone."""

    zone: str
    positive_hits: tuple[str, ...] = ()
    supporting_hits: tuple[str, ...] = ()
    refuting_hits: tuple[str, ...] = ()
    unigram_counts: tuple[tuple[str, int], ...] = ()
    bigram_counts: tuple[tuple[str, int], ...] = ()
    trigram_counts: tuple[tuple[str, int], ...] = ()
    score: float = 0.0
    vocabulary_version: str = ""


@dataclass(frozen=True, slots=True)
class FamilyClassification:
    """Result of classifying a single table against table families."""

    family: str | None
    confidence: float
    evidence: tuple[VocabularyEvidence, ...] = ()
    structural_confirmed: bool = False
    repair_policy: RepairPolicy = RepairPolicy.NO_REPAIR


@dataclass(frozen=True, slots=True)
class TableFamilySpec:
    """Specification for one table family."""

    name: str
    shape: ShapeConstraint
    evidence_pack: CompiledEvidencePack
    repair_policy: RepairPolicy = RepairPolicy.NO_REPAIR
    candidate_default_scope: TableScope = TableScope.BODY


def build_ngram_tier(
    name: str,
    phrases: tuple[str, ...],
    *,
    priority: int,
    value: int,
    support: bool = False,
    min_distinct_hits: int = 1,
) -> EvidenceTier | None:
    """Build an ngram tier from multi-token phrases, filtering out 1-token terms."""
    valid_ngrams = tuple(p for p in phrases if len(tokenize(p)) >= 2)
    if not valid_ngrams:
        return None
    return EvidenceTier(
        name=name,
        priority=priority,
        value=value,
        terms=valid_ngrams,
        match_kind="ngram",
        min_distinct_hits=min_distinct_hits,
        support=support,
    )
