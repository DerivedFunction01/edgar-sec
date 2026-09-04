"""Balance sheet (Financial Position) line item concepts."""

from __future__ import annotations

from defs.taxonomy.tables.shapes import ShapeConstraint
from defs.taxonomy.tables.specs import (
    RepairPolicy,
    TableFamilySpec,
    TableScope,
    build_ngram_tier,
)
from defs.text.bow import LexicalEvidencePack, compile_evidence_pack

ASSETS_TERMS: tuple[str, ...] = (
    "total assets",
    "total current assets",
    "current assets",
)

LIABILITIES_TERMS: tuple[str, ...] = (
    "total liabilities",
    "total current liabilities",
    "current liabilities",
)

EQUITY_TERMS: tuple[str, ...] = (
    "total stockholders' equity",
    "total shareholders' equity",
    "total stockholders equity",
    "total shareholders equity",
    "total equity",
    "stockholders' equity",
    "shareholders' equity",
    "retained earnings",
    "common stock",
    "additional paid-in capital",
)

CASH_TERMS: tuple[str, ...] = (
    "cash and cash equivalents",
    "cash and equivalents",
    "marketable securities",
    "short-term investments",
)

BALANCE_SHEET_VETOES: tuple[str, ...] = ("activities",)

_bs_primary: tuple[str, ...] = (
    *ASSETS_TERMS,
    *LIABILITIES_TERMS,
    *EQUITY_TERMS,
)

_BALANCE_SHEET_PACK = compile_evidence_pack(
    LexicalEvidencePack(
        name="balance_sheet",
        tiers=tuple(
            t
            for t in (
                build_ngram_tier(
                    "bs_lines",
                    _bs_primary,
                    priority=10,
                    value=2,
                    min_distinct_hits=2,
                ),
            )
            if t is not None
        ),
        exclusion_terms=BALANCE_SHEET_VETOES,
    )
)

BALANCE_SHEET_SPEC = TableFamilySpec(
    name="balance_sheet",
    shape=ShapeConstraint(
        min_rows=8, max_rows=65, min_cols=2, min_numeric_density=0.15
    ),
    evidence_pack=_BALANCE_SHEET_PACK,
    repair_policy=RepairPolicy.SAFE_GRID_REPAIR,
    candidate_default_scope=TableScope.BODY,
)
