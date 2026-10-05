"""ASC 718 Stock-based compensation rollforward concepts."""

from __future__ import annotations

from edgar_sec.domain.taxonomy.schedules.compensation.stock_comp import (
    STOCK_COMP_PRIMARY_TERMS,
    STOCK_COMP_SUPPORTING_TERMS,
    STOCK_COMP_VETOES,
)
from edgar_sec.domain.taxonomy.tables.shapes import ShapeConstraint
from edgar_sec.domain.taxonomy.tables.specs import (
    RepairPolicy,
    TableFamilySpec,
    TableScope,
    build_ngram_tier,
)
from edgar_sec.foundation.text.evidence import (
    LexicalEvidencePack,
    compile_evidence_pack,
)

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
