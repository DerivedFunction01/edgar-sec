"""Representation facade for page-marker analysis and policy application.

The single supported dispatch surface for callers: ASCII analysis and the
string-first HTML adapter never expose DOM coordinate frames, and callers do
not branch into a legacy HTML page-marker implementation.
"""

from __future__ import annotations

from typing import Any

from .ascii.orchestrator import analyze_page_markers as _analyze_ascii
from .ascii.orchestrator import apply_page_markers as _apply_ascii_policy
from .models import (
    PageArtifactPolicy,
    PageBreakArtifact,
    PageMarkerAnalysis,
    PageMarkerTerminalState,
)


def analyze_page_markers(
    document: str,
    context: dict[str, Any] | None = None,
    *,
    representation: str = "ascii",
    allow_letter_number: bool = True,
) -> PageMarkerAnalysis:
    """Analyze page markers in the declared representation frame.

    ``"ascii"`` delegates to the ASCII orchestrator. HTML callers use
    :func:`apply_html_policy`, which renders a text frame before analysis.
    """

    if representation.casefold() == "html":
        return PageMarkerAnalysis(
            (),
            (),
            (),
            representation=representation,
            source_text=document,
            terminal_state=PageMarkerTerminalState.NO_VISIBLE_LABELS,
        )
    from .ascii.orchestrator import analyze_page_markers as _analyze_ascii

    return _analyze_ascii(
        document,
        context,
        representation=representation,
        allow_letter_number=allow_letter_number,
    )


def apply_html_policy(
    html: str,
    analysis: PageMarkerAnalysis | None = None,
    policy: PageArtifactPolicy = PageArtifactPolicy.STRIP,
    *,
    first_id: int = 1,
    allow_letter_number: bool = True,
) -> tuple[
    str,
    PageMarkerAnalysis,
    tuple[PageBreakArtifact, ...],
    dict[str, dict],
    int,
    tuple,
]:
    """Apply page policy to HTML input using the string-first fast path."""
    from .fast_html import apply_fast_html_page_policy

    return apply_fast_html_page_policy(
        html,
        analysis,
        policy,
        first_id=first_id,
        allow_letter_number=allow_letter_number,
    )


def apply_text_policy(
    text: str,
    analysis: PageMarkerAnalysis | None = None,
    policy: PageArtifactPolicy = PageArtifactPolicy.STRIP,
    *,
    first_id: int = 1,
) -> tuple[
    str, PageMarkerAnalysis, tuple[PageBreakArtifact, ...], dict[str, dict], int
]:
    """Apply the policy to text-frame decisions via the ASCII orchestrator.

    The returned analysis remains in the ASCII text coordinate frame.
    """

    if analysis is None:
        analysis = _analyze_ascii(text, representation="ascii")
    text, artifacts, templates, next_id = _apply_ascii_policy(
        text, analysis, policy, first_id=first_id
    )
    return text, analysis, artifacts, templates, next_id


__all__ = [
    "analyze_page_markers",
    "apply_html_policy",
    "apply_text_policy",
]
