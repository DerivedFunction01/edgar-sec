"""Statement of Stockholders' Equity and Comprehensive Income terms and tail patterns.

Owns equity statement section labels and tail patterns.
"""

from __future__ import annotations

import re

from edgar_sec.foundation.regex.builder import build_alternation

EQUITY_PRIMARY_TERMS: tuple[str, ...] = (
    "balance at",
    "additional paid-in capital",
    "accumulated other comprehensive",
    "retained earnings",
    "common stock",
    "treasury stock",
    "shares outstanding",
    "comprehensive income",
)

EQUITY_SUPPORTING_TERMS: tuple[str, ...] = (
    "stock-based compensation",
    "dividends declared",
    "net income",
    "repurchase of common stock",
)

EQUITY_STATEMENT_TAIL_TERMS: tuple[str, ...] = (
    "balance at beginning of period",
    "balance at end of period",
    "ending balance",
    "beginning balance",
    "total stockholders' equity",
    "total shareholders' equity",
    "total equity",
)

_EQUITY_STATEMENT_TAIL_PATTERN = build_alternation(
    EQUITY_STATEMENT_TAIL_TERMS,
    auto_escape=True,
    flexible_whitespace=True,
    compact=True,
)

EQUITY_STATEMENT_TAIL_RE = re.compile(
    rf"^\s*{_EQUITY_STATEMENT_TAIL_PATTERN}(?=\s|$)", re.IGNORECASE
)

EQUITY_VETOES: tuple[str, ...] = ("activities",)

from edgar_sec.domain.taxonomy.tables.shapes import ShapeConstraint
from edgar_sec.domain.taxonomy.tables.specs import (
    RepairPolicy,
    TableFamilySpec,
    TableScope,
    build_ngram_tier,
)
from edgar_sec.foundation.text.evidence import (
    LexicalEvidencePack,
    compile_evidence_pack,
)

_EQUITY_PACK = compile_evidence_pack(
    LexicalEvidencePack(
        name="equity_statement",
        tiers=tuple(
            t
            for t in (
                build_ngram_tier(
                    "equity_primary",
                    EQUITY_PRIMARY_TERMS,
                    priority=10,
                    value=2,
                    min_distinct_hits=2,
                ),
                build_ngram_tier(
                    "equity_support",
                    EQUITY_SUPPORTING_TERMS,
                    priority=5,
                    value=1,
                    support=True,
                ),
            )
            if t is not None
        ),
        exclusion_terms=EQUITY_VETOES,
    )
)

EQUITY_STATEMENT_SPEC = TableFamilySpec(
    name="equity_statement",
    shape=ShapeConstraint(
        min_rows=5, max_rows=120, min_cols=3, min_numeric_density=0.15
    ),
    evidence_pack=_EQUITY_PACK,
    repair_policy=RepairPolicy.SAFE_GRID_REPAIR,
    candidate_default_scope=TableScope.BODY,
    priority=100,
)

__all__ = [
    "EQUITY_PRIMARY_TERMS",
    "EQUITY_STATEMENT_SPEC",
    "EQUITY_STATEMENT_TAIL_RE",
    "EQUITY_STATEMENT_TAIL_TERMS",
    "EQUITY_SUPPORTING_TERMS",
    "EQUITY_VETOES",
]
