"""Goodwill and intangible assets disaggregation and amortization schedules (ASC 350)."""

from __future__ import annotations

from defs.taxonomy.tables.shapes import ShapeConstraint
from defs.taxonomy.tables.specs import (
    RepairPolicy,
    TableFamilySpec,
    TableScope,
    build_ngram_tier,
)
from defs.text.bow import LexicalEvidencePack, compile_evidence_pack
from defs.text.compounds import (
    expand_alternations,
    expand_compounds,
    expand_variants,
)

# Primary Tier: Intangible asset classes, amortization rows, and future amortization schedules
_INTANGIBLE_CLASSES = (
    "customer relationships",
    "customer contracts and relationships",
    "developed technology",
    "patents and technology",
    "trademarks and trade names",
    "proprietary technology",
    "in-process research and development",
    "unpatented technology",
    "favorable lease terms",
    "non-compete agreements",
    "finite-lived intangible assets",
    "indefinite-lived intangible assets",
    "total intangible assets",
    "goodwill by reporting unit",
    "carrying amount of goodwill",
)

_AMORTIZATION_TERMS = (
    "accumulated amortization",
    "less: accumulated amortization",
    "less accumulated amortization",
    "gross carrying amount",
    "net carrying amount",
    "amortization expense",
    "future amortization expense",
    "estimated amortization expense",
    "annual amortization expense",
    "weighted average amortization period",
    "weighted-average remaining useful life",
)

_FUTURE_YEARS = expand_compounds(
    ("year ending", "years ending", "fiscal year ending", "for the year ended"),
    (
        "december 31",
        "december 31,",
        "january 31",
        "january 31,",
        "september 30",
        "september 30,",
    ),
)

INTANGIBLES_PRIMARY_TERMS: tuple[str, ...] = expand_alternations(
    _INTANGIBLE_CLASSES,
    _AMORTIZATION_TERMS,
    _FUTURE_YEARS,
    expand_compounds(
        ("intangible assets consist of", "intangible assets consisted of"),
    ),
    expand_compounds(
        (
            "goodwill and intangible assets consisted of",
            "goodwill and other intangible assets",
        ),
    ),
)

# Supporting Tier: Intangibles vocabulary, amortization metrics, and reporting units
INTANGIBLES_SUPPORTING_TERMS: tuple[str, ...] = expand_alternations(
    expand_variants(
        ("intangible", "intangibles", "goodwill", "amortization", "impairment")
    ),
    "reporting unit",
    "reporting units",
    "useful life",
    "useful lives",
    "thereafter",
)

INTANGIBLES_VETOES: tuple[str, ...] = ("activities",)

_INTANGIBLES_PACK = compile_evidence_pack(
    LexicalEvidencePack(
        name="intangibles",
        tiers=tuple(
            t
            for t in (
                build_ngram_tier(
                    "intangibles_primary",
                    INTANGIBLES_PRIMARY_TERMS,
                    priority=10,
                    value=2,
                    min_distinct_hits=2,
                ),
                build_ngram_tier(
                    "intangibles_support",
                    INTANGIBLES_SUPPORTING_TERMS,
                    priority=5,
                    value=1,
                    support=True,
                ),
            )
            if t is not None
        ),
        exclusion_terms=INTANGIBLES_VETOES,
    )
)

INTANGIBLES_SPEC = TableFamilySpec(
    name="intangibles",
    shape=ShapeConstraint(
        min_rows=3, max_rows=40, min_cols=2, min_numeric_density=0.10
    ),
    evidence_pack=_INTANGIBLES_PACK,
    repair_policy=RepairPolicy.SAFE_GRID_REPAIR,
    candidate_default_scope=TableScope.BODY,
    priority=50,
)

__all__ = [
    "INTANGIBLES_PRIMARY_TERMS",
    "INTANGIBLES_SPEC",
    "INTANGIBLES_SUPPORTING_TERMS",
    "INTANGIBLES_VETOES",
]
