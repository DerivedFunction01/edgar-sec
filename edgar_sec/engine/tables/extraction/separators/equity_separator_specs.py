"""Equity-statement separator specs (TEST_EQUITY_SEPARATOR).

Registry data for the routed elimination cascade: the
dated-balance bookend core, the claim-local legs in firing
order, and the assignment pass's supporting-point inputs.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EquitySeparatorSpec:
    """One family's routed separator: legs as priced data."""

    family: str
    max_rows: int
    span_years_min: int
    stub_keys: tuple[str, ...]
    header_tokens: tuple[str, ...]
    core_vocab: tuple[str, ...]
    flow_stub_keys: tuple[str, ...]
    flow_prefix: str
    component_keys: tuple[str, ...]
    component_header_tokens: tuple[str, ...]


EQUITY_SEPARATOR_SPECS: dict[str, EquitySeparatorSpec] = {
    "equity_statement": EquitySeparatorSpec(
        family="equity_statement",
        max_rows=5,
        span_years_min=3,
        stub_keys=(
            "total",
            "average common shares outstanding assuming dilution",
            "current liabilities",
            "effect of dilutive securities",
        ),
        header_tokens=("purchase",),
        core_vocab=(
            "balance",
            "balance at",
            "net income",
            "net loss",
            "stock based compensation",
        ),
        flow_stub_keys=(
            "comprehensive income",
            "net income",
            "net loss",
            "other comprehensive income",
        ),
        flow_prefix="comprehensive income",
        component_keys=(
            "common stock",
            "preferred stock",
            "retained earnings",
            "additional paid in capital",
            "paid in capital",
            "treasury stock",
            "contributed capital",
            "accumulated deficit",
            "dividends",
            "share repurchase",
            "shares issued",
            "mezzanine equity",
            "member s equity",
            "members equity",
        ),
        component_header_tokens=(
            "common",
            "preferred",
            "treasury",
            "mezzanine",
            "retained",
            "contributed",
            "member",
        ),
    ),
}
