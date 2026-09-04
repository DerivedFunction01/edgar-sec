"""Statement of cash flows line item concepts."""

from __future__ import annotations

from defs.taxonomy.tables.shapes import ShapeConstraint
from defs.taxonomy.tables.specs import (
    RepairPolicy,
    TableFamilySpec,
    TableScope,
    build_ngram_tier,
)
from defs.text.bow import LexicalEvidencePack, compile_evidence_pack

OPERATING_ACTIVITIES_TERMS: tuple[str, ...] = (
    "operating activities",
    "cash flows from operating activities",
    "net cash provided by operating activities",
    "net cash used in operating activities",
    "net cash provided by (used in) operating activities",
)

INVESTING_ACTIVITIES_TERMS: tuple[str, ...] = (
    "investing activities",
    "cash flows from investing activities",
    "net cash provided by investing activities",
    "net cash used in investing activities",
    "net cash used in (provided by) investing activities",
)

FINANCING_ACTIVITIES_TERMS: tuple[str, ...] = (
    "financing activities",
    "cash flows from financing activities",
    "net cash provided by financing activities",
    "net cash used in financing activities",
    "net cash provided by (used in) financing activities",
)

CASH_FLOW_ACTIVITIES_TRIO: tuple[str, ...] = (
    "operating activities",
    "investing activities",
    "financing activities",
)

_cf_primary: tuple[str, ...] = (
    *OPERATING_ACTIVITIES_TERMS,
    *INVESTING_ACTIVITIES_TERMS,
    *FINANCING_ACTIVITIES_TERMS,
    *CASH_FLOW_ACTIVITIES_TRIO,
)

_CASH_FLOW_PACK = compile_evidence_pack(
    LexicalEvidencePack(
        name="cash_flow",
        tiers=tuple(
            t
            for t in (
                build_ngram_tier(
                    "cf_activities",
                    _cf_primary,
                    priority=10,
                    value=2,
                    min_distinct_hits=2,
                ),
            )
            if t is not None
        ),
    )
)

CASH_FLOW_SPEC = TableFamilySpec(
    name="cash_flow",
    shape=ShapeConstraint(
        min_rows=12, max_rows=85, min_cols=2, min_numeric_density=0.15
    ),
    evidence_pack=_CASH_FLOW_PACK,
    repair_policy=RepairPolicy.SAFE_GRID_REPAIR,
    candidate_default_scope=TableScope.BODY,
    priority=100,
)
