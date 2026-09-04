"""Inventory disaggregation, valuation, and reserve schedules (ASC 330)."""

from __future__ import annotations

from defs.taxonomy.tables.shapes import ShapeConstraint
from defs.taxonomy.tables.specs import (
    RepairPolicy,
    TableFamilySpec,
    TableScope,
    build_ngram_tier,
)
from defs.text.bow import LexicalEvidencePack, compile_evidence_pack
from defs.text.compounds import (
    expand_alternations,
    expand_compounds,
    expand_variants,
)

# Primary Tier: Distinctive inventory disaggregation row stubs
_INVENTORY_CLASSES = (
    "raw material",
    "raw materials",
    "work in process",
    "work in progress",
    "finished good",
    "finished goods",
    "merchandise",
    "merchandise inventories",
    "parts and accessories",
    "manufacturing supplies",
    "service parts",
    "inventories at cost",
    "total inventories at cost",
    "gross inventories",
    "inventories, gross",
)

_VALUATION_RESERVES = (
    "fifo cost",
    "lifo reserve",
    "lifo effect",
    "lifo inventory reserve",
    "excess of current cost over stated lifo value",
    "lower of cost or market",
    "lower of cost or net realizable value",
    "obsolescence reserve",
    "inventory reserve",
    "inventory valuation allowance",
    "shrinkage reserve",
)

INVENTORY_PRIMARY_TERMS: tuple[str, ...] = expand_alternations(
    _INVENTORY_CLASSES,
    _VALUATION_RESERVES,
    expand_compounds(
        (
            "inventories consist of",
            "inventories comprised of",
            "components of inventory",
            "components of inventories",
        ),
    ),
    expand_compounds(
        (
            "inventories are summarized as follows",
            "inventories consisted of the following",
        ),
    ),
)

# Supporting Tier: Inventory headers, units, and inventory types
INVENTORY_SUPPORTING_TERMS: tuple[str, ...] = expand_alternations(
    expand_variants(("inventory", "inventories", "raw material", "finished good")),
    "fifo",
    "lifo",
    "net realizable value",
    "average cost",
    "inventories, net",
    "total inventories",
    "total inventory",
)

INVENTORY_VETOES: tuple[str, ...] = ("activities",)

_INVENTORY_PACK = compile_evidence_pack(
    LexicalEvidencePack(
        name="inventory",
        tiers=tuple(
            t
            for t in (
                build_ngram_tier(
                    "inventory_primary",
                    INVENTORY_PRIMARY_TERMS,
                    priority=10,
                    value=2,
                    min_distinct_hits=2,
                ),
                build_ngram_tier(
                    "inventory_support",
                    INVENTORY_SUPPORTING_TERMS,
                    priority=5,
                    value=1,
                    support=True,
                ),
            )
            if t is not None
        ),
        exclusion_terms=INVENTORY_VETOES,
    )
)

INVENTORY_SPEC = TableFamilySpec(
    name="inventory",
    shape=ShapeConstraint(
        min_rows=3, max_rows=30, min_cols=2, min_numeric_density=0.10
    ),
    evidence_pack=_INVENTORY_PACK,
    repair_policy=RepairPolicy.SAFE_GRID_REPAIR,
    candidate_default_scope=TableScope.BODY,
    priority=50,
)

__all__ = [
    "INVENTORY_PRIMARY_TERMS",
    "INVENTORY_SPEC",
    "INVENTORY_SUPPORTING_TERMS",
    "INVENTORY_VETOES",
]
