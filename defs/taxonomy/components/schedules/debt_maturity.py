"""ASC 470 Debt principal maturities schedule concepts."""

from __future__ import annotations

from defs.taxonomy.tables.shapes import ShapeConstraint
from defs.taxonomy.tables.specs import (
    RepairPolicy,
    TableFamilySpec,
    TableScope,
    build_ngram_tier,
)
from defs.text.bow import LexicalEvidencePack, compile_evidence_pack

DEBT_MATURITY_PRIMARY_TERMS: tuple[str, ...] = (
    "principal maturities",
    "aggregate maturities",
    "maturities of long-term debt",
    "maturities of debt",
    "sinking fund requirements",
    "sinking fund",
    "annual maturities of long-term debt",
)

DEBT_MATURITY_SUPPORTING_TERMS: tuple[str, ...] = (
    "senior notes",
    "term loan",
    "credit facility",
    "thereafter",
    "total long-term debt",
    "revolving credit",
)

DEBT_MATURITY_VETOES: tuple[str, ...] = ("activities",)

_DEBT_MATURITY_PACK = compile_evidence_pack(
    LexicalEvidencePack(
        name="debt_maturity",
        tiers=tuple(
            t
            for t in (
                build_ngram_tier(
                    "debt_primary",
                    DEBT_MATURITY_PRIMARY_TERMS,
                    priority=10,
                    value=2,
                    min_distinct_hits=1,
                ),
                build_ngram_tier(
                    "debt_support",
                    DEBT_MATURITY_SUPPORTING_TERMS,
                    priority=5,
                    value=1,
                    support=True,
                ),
            )
            if t is not None
        ),
        exclusion_terms=DEBT_MATURITY_VETOES,
    )
)

DEBT_MATURITY_SPEC = TableFamilySpec(
    name="debt_maturity",
    shape=ShapeConstraint(
        min_rows=4, max_rows=30, min_cols=2, min_numeric_density=0.20
    ),
    evidence_pack=_DEBT_MATURITY_PACK,
    repair_policy=RepairPolicy.FAMILY_TEMPLATE,
    candidate_default_scope=TableScope.BODY,
)
