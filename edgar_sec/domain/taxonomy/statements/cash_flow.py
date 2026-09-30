"""Statement of cash flows line item concepts and structural tail patterns.

Ported from v1 defs/taxonomy/components/financials/cash_flow.py with exact empirical
filing definitions. Owns cash flow section labels and tail patterns.
"""

from __future__ import annotations

import re

from edgar_sec.foundation.regex.builder import build_alternation

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
    "supplemental disclosures",
    "supplemental cash flow disclosures",
    "supplemental cash flow information",
)

CASH_FLOW_TAIL_TERMS: tuple[str, ...] = (
    "cash and cash equivalents at end of year",
    "cash and cash equivalents at end of period",
    "cash and cash equivalents at beginning of year",
    "cash and cash equivalents at beginning of period",
    "net increase in cash and cash equivalents",
    "net decrease in cash and cash equivalents",
)

_CASH_FLOW_TAIL_PATTERN = build_alternation(
    CASH_FLOW_TAIL_TERMS,
    auto_escape=True,
    flexible_whitespace=True,
    compact=True,
)

CASH_FLOW_TAIL_RE = re.compile(rf"^\s*{_CASH_FLOW_TAIL_PATTERN}(?=\s|$)", re.IGNORECASE)

CASH_FLOW_VETOES: tuple[str, ...] = ("balance sheet",)

__all__ = [
    "CASH_FLOW_ACTIVITIES_TRIO",
    "CASH_FLOW_TAIL_RE",
    "CASH_FLOW_TAIL_TERMS",
    "CASH_FLOW_VETOES",
    "FINANCING_ACTIVITIES_TERMS",
    "INVESTING_ACTIVITIES_TERMS",
    "OPERATING_ACTIVITIES_TERMS",
]
