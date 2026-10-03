"""TableFamilySpec definitions for derivatives & hedging disclosures (ASC 815) and AOCI (ASC 220)."""

from __future__ import annotations

from edgar_sec.domain.taxonomy.schedules.derivatives.aoci import (
    AOCI_PRIMARY_TERMS,
    AOCI_SECONDARY_TERMS,
)
from edgar_sec.domain.taxonomy.schedules.derivatives.cp import (
    COMMODITY_DERIVATIVE_TERMS,
)
from edgar_sec.domain.taxonomy.schedules.derivatives.credit import (
    CREDIT_DERIVATIVE_TERMS,
)
from edgar_sec.domain.taxonomy.schedules.derivatives.eq import EQUITY_DERIVATIVE_TERMS
from edgar_sec.domain.taxonomy.schedules.derivatives.fx import FX_DERIVATIVE_TERMS
from edgar_sec.domain.taxonomy.schedules.derivatives.generic import (
    DERIVATIVE_HEADING_TERMS,
    GENERIC_DERIVATIVE_TERMS,
)
from edgar_sec.domain.taxonomy.schedules.derivatives.guards import (
    NON_DERIVATIVE_EXCLUSIONS,
)
from edgar_sec.domain.taxonomy.schedules.derivatives.ir import IR_DERIVATIVE_TERMS
from edgar_sec.domain.taxonomy.tables.shapes import ShapeConstraint
from edgar_sec.domain.taxonomy.tables.specs import (
    RepairPolicy,
    TableFamilySpec,
    TableScope,
    build_ngram_tier,
)
from edgar_sec.foundation.text.compounds import expand_alternations
from edgar_sec.foundation.text.evidence import (
    LexicalEvidencePack,
    compile_evidence_pack,
)

DERIVATIVES_PRIMARY_TERMS: tuple[str, ...] = expand_alternations(
    IR_DERIVATIVE_TERMS,
    FX_DERIVATIVE_TERMS,
    COMMODITY_DERIVATIVE_TERMS,
    EQUITY_DERIVATIVE_TERMS,
    CREDIT_DERIVATIVE_TERMS,
    GENERIC_DERIVATIVE_TERMS,
)

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
