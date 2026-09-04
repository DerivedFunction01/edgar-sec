"""ASC 740 Income tax rate reconciliation concepts."""

from __future__ import annotations

from defs.taxonomy.tables.shapes import ShapeConstraint
from defs.taxonomy.tables.specs import (
    RepairPolicy,
    TableFamilySpec,
    TableScope,
    build_ngram_tier,
)
from defs.text.bow import LexicalEvidencePack, compile_evidence_pack

TAX_RECONCILIATION_PRIMARY_TERMS: tuple[str, ...] = (
    "federal statutory rate",
    "federal statutory income tax",
    "statutory federal income tax rate",
    "effective tax rate",
    "rate reconciliation",
    "income taxes at statutory rate",
    "foreign rate differential",
    "state and local income taxes",
    "tax expense at statutory rate",
)

TAX_RECONCILIATION_SUPPORTING_TERMS: tuple[str, ...] = (
    "valuation allowance",
    "tax credits",
    "nondeductible expenses",
    "effective income tax rate",
)

TAX_RECONCILIATION_VETOES: tuple[str, ...] = ("activities",)

_TAX_RECONCILIATION_PACK = compile_evidence_pack(
    LexicalEvidencePack(
        name="tax_reconciliation",
        tiers=tuple(
            t
            for t in (
                build_ngram_tier(
                    "tax_recon_primary",
                    TAX_RECONCILIATION_PRIMARY_TERMS,
                    priority=10,
                    value=2,
                    min_distinct_hits=1,
                ),
                build_ngram_tier(
                    "tax_recon_support",
                    TAX_RECONCILIATION_SUPPORTING_TERMS,
                    priority=5,
                    value=1,
                    support=True,
                ),
            )
            if t is not None
        ),
        exclusion_terms=TAX_RECONCILIATION_VETOES,
    )
)

TAX_RECONCILIATION_SPEC = TableFamilySpec(
    name="tax_reconciliation",
    shape=ShapeConstraint(
        min_rows=4, max_rows=35, min_cols=2, min_numeric_density=0.15
    ),
    evidence_pack=_TAX_RECONCILIATION_PACK,
    repair_policy=RepairPolicy.FAMILY_TEMPLATE,
    candidate_default_scope=TableScope.BODY,
)
