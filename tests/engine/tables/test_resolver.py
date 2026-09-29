"""Unit tests for edgar_sec.engine.tables.resolver."""

from __future__ import annotations

from edgar_sec.engine.reflow.types import (
    ACTION_TAG_AND_PRESERVE,
    SpanDecision,
)
from edgar_sec.engine.tables.resolver import resolve_table_regions


def test_resolve_table_regions_empty() -> None:
    res = resolve_table_regions([], [])
    assert res == []


def test_resolve_table_regions_valid_table() -> None:
    blocks = [
        (
            0,
            3,
            (
                "Revenue    2024    2023",
                "Product    $100    $90",
                "Service    $200    $180",
            ),
        )
    ]
    decisions = [
        SpanDecision(
            ACTION_TAG_AND_PRESERVE,
            0,
            3,
            0.9,
            ("repeated_numeric_columns:2",),
            "table_rule",
        )
    ]
    resolved = resolve_table_regions(decisions, blocks)
    assert len(resolved) == 1
    assert resolved[0].action == ACTION_TAG_AND_PRESERVE
