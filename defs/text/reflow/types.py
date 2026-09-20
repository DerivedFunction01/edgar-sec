"""Immutable data models and action constants for ASCII reflow."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from defs.tables.protection import TableSpan
from defs.text.signatures import SignatureRegion

ACTION_UNWRAP = "unwrap"
ACTION_PRESERVE = "preserve"
ACTION_TAG_AND_PRESERVE = "tag_and_preserve"

_MIN_PROSE_ALPHA_DENSITY = 0.55


@dataclass(frozen=True, slots=True)
class ReflowPolicy:
    """Controls whether prose before the body boundary may be unwrapped."""

    unwrap_pre_body_prose: bool = False
    split_structural_boundaries: bool = True
    split_bullet_items: bool = True
    relax_prose_layout_gaps: bool = False
    unwrap_bullet_continuations: bool = False
    is_checkbox_answer_line: Callable[[str], bool] | None = None
    is_page_boundary_line: Callable[[str], bool] | None = None
    is_structural_line: Callable[[str], bool] | None = None
    split_table_intro: (
        Callable[[tuple[str, ...]], tuple[tuple[str, ...], tuple[str, ...]]] | None
    ) = None


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
    protected_signatures: tuple[SignatureRegion, ...] = ()


__all__ = [
    "ACTION_PRESERVE",
    "ACTION_TAG_AND_PRESERVE",
    "ACTION_UNWRAP",
    "_MIN_PROSE_ALPHA_DENSITY",
    "ReflowPolicy",
    "ReflowResult",
    "SpanDecision",
]
