"""ASC 820 Fair value measurement hierarchy concepts."""

from __future__ import annotations

from defs.taxonomy.tables.shapes import ShapeConstraint
from defs.taxonomy.tables.specs import (
    RepairPolicy,
    TableFamilySpec,
    TableScope,
    build_ngram_tier,
)
from defs.text.bow import LexicalEvidencePack, compile_evidence_pack

FAIR_VALUE_PRIMARY_TERMS: tuple[str, ...] = (
    "level 1",
    "level 2",
    "level 3",
    "level #",
    "observable inputs",
    "unobservable inputs",
    "quoted prices",
    "fair value hierarchy",
    "fair value measurement",
    "total fair value",
)

FAIR_VALUE_SUPPORTING_TERMS: tuple[str, ...] = (
    "market approach",
    "income approach",
    "discounted cash flow",
    "carrying amount",
)

FAIR_VALUE_VETOES: tuple[str, ...] = ("activities",)

_FAIR_VALUE_PACK = compile_evidence_pack(
    LexicalEvidencePack(
        name="fair_value",
        tiers=tuple(
            t
            for t in (
                build_ngram_tier(
                    "fair_value_primary",
                    FAIR_VALUE_PRIMARY_TERMS,
                    priority=10,
                    value=2,
                    min_distinct_hits=2,
                ),
                build_ngram_tier(
                    "fair_value_support",
                    FAIR_VALUE_SUPPORTING_TERMS,
                    priority=5,
                    value=1,
                    support=True,
                ),
            )
            if t is not None
        ),
        exclusion_terms=FAIR_VALUE_VETOES,
    )
)

FAIR_VALUE_SPEC = TableFamilySpec(
    name="fair_value",
    shape=ShapeConstraint(
        min_rows=3, max_rows=80, min_cols=3, min_numeric_density=0.15
    ),
    evidence_pack=_FAIR_VALUE_PACK,
    repair_policy=RepairPolicy.FAMILY_TEMPLATE,
    candidate_default_scope=TableScope.BODY,
)
