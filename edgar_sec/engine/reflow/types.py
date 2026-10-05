"""Immutable decision vocabulary and injected policy for ASCII reflow.
The engine owns no form vocabulary: everything that needs to know what a checkbox answer or a section label looks like arrives on `ReflowPolicy`. A predicate left `None` contributes nothing, so a caller that cares about a shape must supply it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from edgar_sec.engine.document.page_markers.signatures import SignatureRegion
from edgar_sec.engine.tables.protection.tags import TableSpan

ACTION_UNWRAP = "unwrap"
ACTION_PRESERVE = "preserve"
ACTION_TAG_AND_PRESERVE = "tag_and_preserve"

_MIN_PROSE_ALPHA_DENSITY = 0.55


@dataclass(frozen=True, slots=True)
class ReflowPolicy:
    """Controls whether prose before the body boundary may be unwrapped.
    The five ``is_*`` fields carry the caller's domain predicates; ``split_table_intro`` overrides how a narrative line is separated from its grid.
    """

    unwrap_pre_body_prose: bool = False
    split_structural_boundaries: bool = True
    split_bullet_items: bool = True
    relax_prose_layout_gaps: bool = False
    unwrap_bullet_continuations: bool = False
    is_checkbox_answer_line: Callable[[str], bool] | None = None
    is_page_boundary_line: Callable[[str], bool] | None = None
    is_structural_line: Callable[[str], bool] | None = None
    is_table_bridge_line: Callable[[str], bool] | None = None
    is_table_tail_line: Callable[[str], bool] | None = None
    tag_untagged_tables: bool = True
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
