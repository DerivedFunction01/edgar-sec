"""Income statement (Operations / Profit or Loss) line item concepts."""

from __future__ import annotations

from defs.taxonomy.tables.shapes import ShapeConstraint
from defs.taxonomy.tables.specs import (
    RepairPolicy,
    TableFamilySpec,
    TableScope,
    build_ngram_tier,
)
from defs.text.bow import LexicalEvidencePack, compile_evidence_pack

REVENUE_TERMS: tuple[str, ...] = (
    "total revenues",
    "total revenue",
    "total net revenues",
    "total net sales",
    "net sales",
    "revenues",
    "revenue",
    "sales and service revenues",
)

COST_OF_SALES_TERMS: tuple[str, ...] = (
    "cost of revenue",
    "cost of revenues",
    "cost of sales",
    "cost of goods sold",
    "costs of sales",
)

GROSS_PROFIT_TERMS: tuple[str, ...] = (
    "gross profit",
    "gross margin",
)

OPERATING_EXPENSES_TERMS: tuple[str, ...] = (
    "total operating expenses",
    "operating expenses",
    "research and development",
    "selling, general and administrative",
    "general and administrative",
    "sales and marketing",
)

OPERATING_INCOME_TERMS: tuple[str, ...] = (
    "operating income",
    "operating loss",
    "operating income (loss)",
    "income from operations",
    "loss from operations",
)

PRETAX_INCOME_TERMS: tuple[str, ...] = (
    "income before income taxes",
    "income before provision for income taxes",
    "income (loss) before income taxes",
    "loss before income taxes",
    "pretax income",
)

NET_INCOME_TERMS: tuple[str, ...] = (
    "net income",
    "net loss",
    "net income (loss)",
    "net earnings",
    "net loss attributable to",
    "net income attributable to",
)

EPS_TERMS: tuple[str, ...] = (
    "basic earnings per share",
    "diluted earnings per share",
    "basic and diluted earnings per share",
    "earnings per share",
    "basic per share",
    "diluted per share",
    "per share - basic",
    "per share - diluted",
)

INCOME_STATEMENT_VETOES: tuple[str, ...] = ("activities",)

_is_primary: tuple[str, ...] = (
    *REVENUE_TERMS,
    *COST_OF_SALES_TERMS,
    *GROSS_PROFIT_TERMS,
    *OPERATING_INCOME_TERMS,
    *NET_INCOME_TERMS,
    *EPS_TERMS,
)

_INCOME_STATEMENT_PACK = compile_evidence_pack(
    LexicalEvidencePack(
        name="income_statement",
        tiers=tuple(
            t
            for t in (
                build_ngram_tier(
                    "primary_statement_lines",
                    _is_primary,
                    priority=10,
                    value=2,
                    min_distinct_hits=2,
                ),
                build_ngram_tier(
                    "opex_support",
                    OPERATING_EXPENSES_TERMS,
                    priority=5,
                    value=1,
                    support=True,
                ),
            )
            if t is not None
        ),
        exclusion_terms=INCOME_STATEMENT_VETOES,
    )
)

INCOME_STATEMENT_SPEC = TableFamilySpec(
    name="income_statement",
    shape=ShapeConstraint(
        min_rows=8, max_rows=55, min_cols=2, min_numeric_density=0.15
    ),
    evidence_pack=_INCOME_STATEMENT_PACK,
    repair_policy=RepairPolicy.SAFE_GRID_REPAIR,
    candidate_default_scope=TableScope.BODY,
)
