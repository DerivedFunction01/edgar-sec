"""Immutable data models and action constants for ASCII reflow."""

from __future__ import annotations

from dataclasses import dataclass

from defs.tables.protection import TableSpan

ACTION_UNWRAP = "unwrap"
ACTION_PRESERVE = "preserve"
ACTION_TAG_AND_PRESERVE = "tag_and_preserve"

_MIN_PROSE_ALPHA_DENSITY = 0.55


@dataclass(frozen=True, slots=True)
class SpanDecision:
    """One block-level action over a half-open line range."""

    action: str
    start_line: int
    end_line: int
    confidence: float
    evidence: tuple[str, ...] = ()
    trace: str = ""


@dataclass(frozen=True, slots=True)
class ReflowResult:
    """Reflowed text plus the per-block decision trace."""

    text: str
    decisions: tuple[SpanDecision, ...] = ()
    protected_tables: tuple[TableSpan, ...] = ()


__all__ = [
    "ACTION_PRESERVE",
    "ACTION_TAG_AND_PRESERVE",
    "ACTION_UNWRAP",
    "_MIN_PROSE_ALPHA_DENSITY",
    "ReflowResult",
    "SpanDecision",
]
