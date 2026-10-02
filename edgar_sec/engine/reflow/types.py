"""Immutable decision vocabulary and injected policy for ASCII reflow.

The reflow engine owns no vocabulary about any particular form. Everything that
depends on knowing what a checkbox answer line is, what a financial statement
section label looks like, or where the body begins arrives on
:class:`ReflowPolicy` from the caller, so this package reads only the injected
predicate and the text it is given. That is what keeps the engine free of any
dependency on the form families above it.

A predicate left ``None`` contributes nothing to the block features that consult
it; the block's fate then rests on the rules that do not, so a caller that cares
about a shape must supply the predicate for it rather than rely on a default.

A :class:`SpanDecision` records half-open ``[start_line, end_line)`` ranges in
the coordinate frame of the text that was passed in, so a caller can map a
decision back onto the source it was made from.
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

    The five ``is_*`` fields carry the caller's domain predicates: cover answer
    lines, page-boundary lines, cover structural lines, statement bridge labels,
    and statement tail labels. ``split_table_intro`` overrides how a narrative
    line is separated from the grid it introduces.
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
