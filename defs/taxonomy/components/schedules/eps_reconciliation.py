"""ASC 260 Earnings Per Share reconciliation concepts."""

from __future__ import annotations

from defs.taxonomy.tables.shapes import ShapeConstraint
from defs.taxonomy.tables.specs import (
    RepairPolicy,
    TableFamilySpec,
    TableScope,
    build_ngram_tier,
)
from defs.text.bow import LexicalEvidencePack, compile_evidence_pack

EPS_RECON_PRIMARY_TERMS: tuple[str, ...] = (
    "weighted-average shares",
    "weighted average shares",
    "dilutive effect",
    "dilutive potential common shares",
    "antidilutive securities",
    "basic per share",
    "diluted per share",
    "basic earnings per share",
    "diluted earnings per share",
    "numerator",
    "denominator",
)

EPS_RECON_SUPPORTING_TERMS: tuple[str, ...] = (
    "stock options",
    "restricted stock",
    "contingently issuable",
    "incremental shares",
)

EPS_RECON_VETOES: tuple[str, ...] = (
    "activities",
    "revenue",
)

_EPS_RECON_PACK = compile_evidence_pack(
    LexicalEvidencePack(
        name="eps_reconciliation",
        tiers=tuple(
            t
            for t in (
                build_ngram_tier(
                    "eps_recon_primary",
                    EPS_RECON_PRIMARY_TERMS,
                    priority=10,
                    value=2,
                    min_distinct_hits=2,
                ),
                build_ngram_tier(
                    "eps_recon_support",
                    EPS_RECON_SUPPORTING_TERMS,
                    priority=5,
                    value=1,
                    support=True,
                ),
            )
            if t is not None
        ),
        exclusion_terms=EPS_RECON_VETOES,
    )
)

EPS_RECONCILIATION_SPEC = TableFamilySpec(
    name="eps_reconciliation",
    shape=ShapeConstraint(
        min_rows=4, max_rows=30, min_cols=2, min_numeric_density=0.15
    ),
    evidence_pack=_EPS_RECON_PACK,
    repair_policy=RepairPolicy.SAFE_GRID_REPAIR,
    candidate_default_scope=TableScope.BODY,
)
