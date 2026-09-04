"""ASC 718 Stock-based compensation rollforward concepts."""

from __future__ import annotations

from defs.taxonomy.tables.shapes import ShapeConstraint
from defs.taxonomy.tables.specs import (
    RepairPolicy,
    TableFamilySpec,
    TableScope,
    build_ngram_tier,
)
from defs.text.bow import LexicalEvidencePack, compile_evidence_pack

STOCK_COMP_PRIMARY_TERMS: tuple[str, ...] = (
    "options outstanding",
    "shares granted",
    "shares exercised",
    "shares forfeited",
    "shares expired",
    "weighted-average exercise price",
    "weighted average exercise price",
    "weighted-average grant date fair value",
    "unrecognized compensation",
    "restricted stock units",
)

STOCK_COMP_SUPPORTING_TERMS: tuple[str, ...] = (
    "stock options",
    "grant date",
    "vesting period",
    "intrinsic value",
    "aggregate intrinsic value",
    "weighted-average remaining contractual term",
)

STOCK_COMP_VETOES: tuple[str, ...] = ("activities",)

_STOCK_COMP_PACK = compile_evidence_pack(
    LexicalEvidencePack(
        name="stock_comp_rollforward",
        tiers=tuple(
            t
            for t in (
                build_ngram_tier(
                    "stock_comp_primary",
                    STOCK_COMP_PRIMARY_TERMS,
                    priority=10,
                    value=2,
                    min_distinct_hits=2,
                ),
                build_ngram_tier(
                    "stock_comp_support",
                    STOCK_COMP_SUPPORTING_TERMS,
                    priority=5,
                    value=1,
                    support=True,
                ),
            )
            if t is not None
        ),
        exclusion_terms=STOCK_COMP_VETOES,
    )
)

STOCK_COMP_ROLLFORWARD_SPEC = TableFamilySpec(
    name="stock_comp_rollforward",
    shape=ShapeConstraint(
        min_rows=4, max_rows=40, min_cols=2, min_numeric_density=0.15
    ),
    evidence_pack=_STOCK_COMP_PACK,
    repair_policy=RepairPolicy.FAMILY_TEMPLATE,
    candidate_default_scope=TableScope.BODY,
)
