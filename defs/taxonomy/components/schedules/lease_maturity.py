"""ASC 842 / 840 Lease commitments and maturity schedule concepts."""

from __future__ import annotations

from defs.taxonomy.tables.shapes import ShapeConstraint
from defs.taxonomy.tables.specs import (
    RepairPolicy,
    TableFamilySpec,
    TableScope,
    build_ngram_tier,
)
from defs.text.bow import LexicalEvidencePack, compile_evidence_pack

LEASE_MATURITY_PRIMARY_TERMS: tuple[str, ...] = (
    "total minimum lease payments",
    "present value of lease",
    "present value of lease liabilities",
    "imputed interest",
    "amount representing interest",
    "future minimum rent",
    "undiscounted lease liabilities",
    "maturities of lease liabilities",
    "undiscounted cash flows",
)

LEASE_MATURITY_SUPPORTING_TERMS: tuple[str, ...] = (
    "operating lease",
    "finance lease",
    "thereafter",
    "total lease liabilities",
    "less imputed interest",
)

LEASE_MATURITY_VETOES: tuple[str, ...] = ("activities",)

_LEASE_MATURITY_PACK = compile_evidence_pack(
    LexicalEvidencePack(
        name="lease_maturity",
        tiers=tuple(
            t
            for t in (
                build_ngram_tier(
                    "lease_primary",
                    LEASE_MATURITY_PRIMARY_TERMS,
                    priority=10,
                    value=2,
                    min_distinct_hits=1,
                ),
                build_ngram_tier(
                    "lease_support",
                    LEASE_MATURITY_SUPPORTING_TERMS,
                    priority=5,
                    value=1,
                    support=True,
                ),
            )
            if t is not None
        ),
        exclusion_terms=LEASE_MATURITY_VETOES,
    )
)

LEASE_MATURITY_SPEC = TableFamilySpec(
    name="lease_maturity",
    shape=ShapeConstraint(
        min_rows=4, max_rows=30, min_cols=2, min_numeric_density=0.20
    ),
    evidence_pack=_LEASE_MATURITY_PACK,
    repair_policy=RepairPolicy.FAMILY_TEMPLATE,
    candidate_default_scope=TableScope.BODY,
)
