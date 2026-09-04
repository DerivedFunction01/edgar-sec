"""ASC 715 Compensation—Retirement benefits (Pension / OPEB) concepts."""

from __future__ import annotations

from defs.taxonomy.tables.shapes import ShapeConstraint
from defs.taxonomy.tables.specs import (
    RepairPolicy,
    TableFamilySpec,
    TableScope,
    build_ngram_tier,
)
from defs.text.bow import LexicalEvidencePack, compile_evidence_pack

PENSION_PRIMARY_TERMS: tuple[str, ...] = (
    "benefit obligation",
    "projected benefit obligation",
    "accumulated benefit obligation",
    "fair value of plan assets",
    "funded status",
    "service cost",
    "interest cost",
    "net periodic benefit cost",
    "actuarial loss",
    "actuarial gain",
)

PENSION_SUPPORTING_TERMS: tuple[str, ...] = (
    "discount rate",
    "expected return on plan assets",
    "rate of compensation increase",
    "benefits paid",
    "employer contributions",
)

PENSION_VETOES: tuple[str, ...] = ("activities",)

_PENSION_PACK = compile_evidence_pack(
    LexicalEvidencePack(
        name="pension",
        tiers=tuple(
            t
            for t in (
                build_ngram_tier(
                    "pension_primary",
                    PENSION_PRIMARY_TERMS,
                    priority=10,
                    value=2,
                    min_distinct_hits=2,
                ),
                build_ngram_tier(
                    "pension_support",
                    PENSION_SUPPORTING_TERMS,
                    priority=5,
                    value=1,
                    support=True,
                ),
            )
            if t is not None
        ),
        exclusion_terms=PENSION_VETOES,
    )
)

PENSION_SPEC = TableFamilySpec(
    name="pension",
    shape=ShapeConstraint(
        min_rows=4, max_rows=60, min_cols=2, min_numeric_density=0.15
    ),
    evidence_pack=_PENSION_PACK,
    repair_policy=RepairPolicy.SAFE_GRID_REPAIR,
    candidate_default_scope=TableScope.BODY,
)
