"""Financial statement section transition bridge terms and patterns.

Ported from v1 defs/taxonomy/components/financials/reflow.py with exact empirical
filing definitions. Owns section label transitions within financial statements.
"""

from __future__ import annotations

import re

from edgar_sec.foundation.regex.builder import build_alternation

FINANCIAL_BRIDGE_TERMS: tuple[str, ...] = (
    "liabilities and stockholders' equity",
    "liabilities and stockholders' deficit",
    "liabilities and shareholders' equity",
    "liabilities and shareholders' deficit",
    "current liabilities",
    "long-term debt",
    "commitments and contingencies",
    "commitments & contingencies",
    "stockholders' equity",
    "shareholders' equity",
    "operating activities",
    "investing activities",
    "financing activities",
    "supplemental cash flow disclosures",
    "supplemental cash flow information",
)

_FINANCIAL_BRIDGE_PATTERN = build_alternation(
    FINANCIAL_BRIDGE_TERMS,
    auto_escape=True,
    flexible_whitespace=True,
    compact=True,
)

FINANCIAL_TABLE_BRIDGE_RE = re.compile(
    rf"^\s*{_FINANCIAL_BRIDGE_PATTERN}(?=\s|:|$)", re.IGNORECASE
)

__all__ = [
    "FINANCIAL_BRIDGE_TERMS",
    "FINANCIAL_TABLE_BRIDGE_RE",
]
