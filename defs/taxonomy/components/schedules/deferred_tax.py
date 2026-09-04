"""ASC 740 Deferred tax assets and liabilities breakdown concepts."""

from __future__ import annotations

from defs.taxonomy.tables.shapes import ShapeConstraint
from defs.taxonomy.tables.specs import (
    RepairPolicy,
    TableFamilySpec,
    TableScope,
    build_ngram_tier,
)
from defs.text.bow import LexicalEvidencePack, compile_evidence_pack

DEFERRED_TAX_PRIMARY_TERMS: tuple[str, ...] = (
    "deferred tax assets",
    "deferred tax liabilities",
    "gross deferred tax assets",
    "gross deferred tax liabilities",
    "net operating loss carryforwards",
    "tax credit carryforwards",
    "total gross deferred tax",
    "net deferred tax asset",
    "net deferred tax liability",
)

DEFERRED_TAX_SUPPORTING_TERMS: tuple[str, ...] = (
    "valuation allowance",
    "depreciation and amortization",
    "accrued expenses",
    "stock-based compensation",
)

DEFERRED_TAX_VETOES: tuple[str, ...] = ("activities",)

_DEFERRED_TAX_PACK = compile_evidence_pack(
    LexicalEvidencePack(
        name="deferred_tax",
        tiers=tuple(
            t
            for t in (
                build_ngram_tier(
                    "deferred_tax_primary",
                    DEFERRED_TAX_PRIMARY_TERMS,
                    priority=10,
                    value=2,
                    min_distinct_hits=1,
                ),
                build_ngram_tier(
                    "deferred_tax_support",
                    DEFERRED_TAX_SUPPORTING_TERMS,
                    priority=5,
                    value=1,
                    support=True,
                ),
            )
            if t is not None
        ),
        exclusion_terms=DEFERRED_TAX_VETOES,
    )
)

DEFERRED_TAX_SPEC = TableFamilySpec(
    name="deferred_tax",
    shape=ShapeConstraint(
        min_rows=4, max_rows=50, min_cols=2, min_numeric_density=0.15
    ),
    evidence_pack=_DEFERRED_TAX_PACK,
    repair_policy=RepairPolicy.SAFE_GRID_REPAIR,
    candidate_default_scope=TableScope.BODY,
)
