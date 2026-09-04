"""Property, plant, and equipment disaggregation schedules (ASC 360)."""

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

# Primary Tier: Asset classes and accumulated depreciation rows
_PPE_ASSET_CLASSES = (
    "land and improvements",
    "land and land improvements",
    "buildings and improvements",
    "building and leasehold improvements",
    "machinery and equipment",
    "furniture and fixtures",
    "leasehold improvements",
    "construction in progress",
    "computer hardware and software",
    "transportation equipment",
    "tools, dies and patterns",
    "property and equipment, gross",
    "property, plant and equipment, gross",
    "total property and equipment, gross",
    "gross property and equipment",
    "gross property, plant and equipment",
)

_DEPRECIATION_ROWS = (
    "accumulated depreciation",
    "accumulated depreciation and amortization",
    "less accumulated depreciation",
    "less: accumulated depreciation",
    "less accumulated depreciation and amortization",
    "less: accumulated depreciation and amortization",
    "total accumulated depreciation",
    "property and equipment, net",
    "property, plant and equipment, net",
    "total property and equipment, net",
    "net property and equipment",
    "net property, plant and equipment",
)

PPE_PRIMARY_TERMS: tuple[str, ...] = expand_alternations(
    _PPE_ASSET_CLASSES,
    _DEPRECIATION_ROWS,
    expand_compounds(
        (
            "property, plant and equipment consists of",
            "property and equipment consisted of",
        ),
    ),
)

# Supporting Tier: Depreciation terminology, useful lives, and asset class stubs
PPE_SUPPORTING_TERMS: tuple[str, ...] = expand_alternations(
    expand_variants(
        ("machinery", "equipment", "fixture", "building", "depreciation", "useful life")
    ),
    "estimated useful life",
    "estimated useful lives",
    "years",
    "straight-line method",
    "depreciable life",
)

PPE_VETOES: tuple[str, ...] = ("activities",)

_PPE_PACK = compile_evidence_pack(
    LexicalEvidencePack(
        name="ppe",
        tiers=tuple(
            t
            for t in (
                build_ngram_tier(
                    "ppe_primary",
                    PPE_PRIMARY_TERMS,
                    priority=10,
                    value=2,
                    min_distinct_hits=2,
                ),
                build_ngram_tier(
                    "ppe_support",
                    PPE_SUPPORTING_TERMS,
                    priority=5,
                    value=1,
                    support=True,
                ),
            )
            if t is not None
        ),
        exclusion_terms=PPE_VETOES,
    )
)

PPE_SPEC = TableFamilySpec(
    name="ppe",
    shape=ShapeConstraint(
        min_rows=3, max_rows=35, min_cols=2, min_numeric_density=0.10
    ),
    evidence_pack=_PPE_PACK,
    repair_policy=RepairPolicy.SAFE_GRID_REPAIR,
    candidate_default_scope=TableScope.BODY,
    priority=50,
)

__all__ = [
    "PPE_PRIMARY_TERMS",
    "PPE_SPEC",
    "PPE_SUPPORTING_TERMS",
    "PPE_VETOES",
]
