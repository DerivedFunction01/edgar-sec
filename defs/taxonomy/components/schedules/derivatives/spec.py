"""TableFamilySpec definitions for derivatives & hedging disclosures (ASC 815) and AOCI (ASC 220)."""

from __future__ import annotations

from defs.taxonomy.components.schedules.derivatives.aoci import (
    AOCI_PRIMARY_TERMS,
    AOCI_SECONDARY_TERMS,
)
from defs.taxonomy.components.schedules.derivatives.cp import COMMODITY_DERIVATIVE_TERMS
from defs.taxonomy.components.schedules.derivatives.credit import (
    CREDIT_DERIVATIVE_TERMS,
)
from defs.taxonomy.components.schedules.derivatives.eq import EQUITY_DERIVATIVE_TERMS
from defs.taxonomy.components.schedules.derivatives.fx import FX_DERIVATIVE_TERMS
from defs.taxonomy.components.schedules.derivatives.generic import (
    DERIVATIVE_HEADING_TERMS,
    GENERIC_DERIVATIVE_TERMS,
)
from defs.taxonomy.components.schedules.derivatives.guards import (
    NON_DERIVATIVE_EXCLUSIONS,
)
from defs.taxonomy.components.schedules.derivatives.ir import IR_DERIVATIVE_TERMS
from defs.taxonomy.tables.shapes import ShapeConstraint
from defs.taxonomy.tables.specs import (
    RepairPolicy,
    TableFamilySpec,
    TableScope,
    build_ngram_tier,
)
from defs.text.bow import LexicalEvidencePack, compile_evidence_pack
from defs.text.compounds import expand_alternations

# Combined Primary Tier for all derivative asset classes, cross-asset structures, and ASC 815 master schedules
DERIVATIVES_PRIMARY_TERMS: tuple[str, ...] = expand_alternations(
    IR_DERIVATIVE_TERMS,
    FX_DERIVATIVE_TERMS,
    COMMODITY_DERIVATIVE_TERMS,
    EQUITY_DERIVATIVE_TERMS,
    CREDIT_DERIVATIVE_TERMS,
    GENERIC_DERIVATIVE_TERMS,
)

# Orthogonal Context Tier: ONLY external accounting standard & risk context (zero repeated instrument terms)
DERIVATIVES_CONTEXT_TERMS: tuple[str, ...] = (
    "asc 815",
    "asc 820",
    "hedge accounting",
    "counterparty credit risk",
    "qualifying hedging relationship",
    "master netting arrangement",
)

DERIVATIVES_VETOES: tuple[str, ...] = NON_DERIVATIVE_EXCLUSIONS

_DERIVATIVES_PACK = compile_evidence_pack(
    LexicalEvidencePack(
        name="derivatives_hedging",
        tiers=tuple(
            t
            for t in (
                build_ngram_tier(
                    "derivatives_primary",
                    DERIVATIVES_PRIMARY_TERMS,
                    priority=10,
                    value=2,
                    min_distinct_hits=1,
                ),
                build_ngram_tier(
                    "derivatives_context",
                    DERIVATIVES_CONTEXT_TERMS,
                    priority=5,
                    value=1,
                    support=True,
                ),
            )
            if t is not None
        ),
        exclusion_terms=DERIVATIVES_VETOES,
    )
)

DERIVATIVES_HEDGING_SPEC = TableFamilySpec(
    name="derivatives_hedging",
    shape=ShapeConstraint(
        min_rows=3, max_rows=60, min_cols=2, min_numeric_density=0.10
    ),
    evidence_pack=_DERIVATIVES_PACK,
    repair_policy=RepairPolicy.SAFE_GRID_REPAIR,
    candidate_default_scope=TableScope.BODY,
    priority=45,
)

_AOCI_PACK = compile_evidence_pack(
    LexicalEvidencePack(
        name="aoci",
        tiers=tuple(
            t
            for t in (
                build_ngram_tier(
                    "aoci_primary",
                    AOCI_PRIMARY_TERMS,
                    priority=10,
                    value=2,
                    min_distinct_hits=1,
                ),
                build_ngram_tier(
                    "aoci_support",
                    AOCI_SECONDARY_TERMS,
                    priority=5,
                    value=1,
                    support=True,
                ),
            )
            if t is not None
        ),
        exclusion_terms=("activities",),
    )
)

AOCI_SPEC = TableFamilySpec(
    name="aoci",
    shape=ShapeConstraint(
        min_rows=3, max_rows=40, min_cols=2, min_numeric_density=0.10
    ),
    evidence_pack=_AOCI_PACK,
    repair_policy=RepairPolicy.SAFE_GRID_REPAIR,
    candidate_default_scope=TableScope.BODY,
    priority=105,
)

__all__ = [
    "AOCI_PRIMARY_TERMS",
    "AOCI_SECONDARY_TERMS",
    "AOCI_SPEC",
    "DERIVATIVES_CONTEXT_TERMS",
    "DERIVATIVES_HEDGING_SPEC",
    "DERIVATIVES_PRIMARY_TERMS",
    "DERIVATIVES_VETOES",
    "DERIVATIVE_HEADING_TERMS",
    "GENERIC_DERIVATIVE_TERMS",
]
