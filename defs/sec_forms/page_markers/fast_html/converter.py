"""High-throughput HTML break-to-text converter and ASCII delegation."""

from __future__ import annotations

import re
from typing import Any

from defs.regex import build_alternation
from defs.text.html import normalize_html_document

from ..ascii.orchestrator import analyze_page_markers as _analyze_ascii
from ..ascii.orchestrator import apply_page_markers as _apply_ascii_policy
from ..models import (
    PageArtifactPolicy,
    PageBreakArtifact,
    PageMarkerAnalysis,
    PageMarkerTerminalState,
)

_BREAK_PROPERTIES = build_alternation(
    ["page-break-before", "page-break-after", "break-before", "break-after"],
    auto_escape=True,
)
_BREAK_VALUES = build_alternation(
    ["always", "page", "all", "left", "right", "recto", "verso"],
    auto_escape=True,
)
_RE_CSS_PAGE_BREAKS = re.compile(
    rf"""<[^>]*style=[\"'][^\"']*(?:{_BREAK_PROPERTIES})\s*:\s*(?:{_BREAK_VALUES})\b[^\"']*[\"'][^>]*>""",
    re.IGNORECASE,
)
_RE_HR_TAGS = re.compile(r"<hr\b[^>]*>", re.IGNORECASE)
_RE_PAGE_TAGS = re.compile(r"</?page\b[^>]*>", re.IGNORECASE)

_PAGE_SENTINEL = "__SEC_PAGE_BREAK_SENTINEL__"


def convert_html_to_break_text(html: str) -> str:
    """Convert HTML to clean text stream with normalized <PAGE> sentinels."""
    if not html:
        return ""
    text = _RE_PAGE_TAGS.sub(f"\n{_PAGE_SENTINEL}\n", html)
    text = _RE_HR_TAGS.sub(f"\n{_PAGE_SENTINEL}\n", text)
    text = _RE_CSS_PAGE_BREAKS.sub(f"\n{_PAGE_SENTINEL}\n", text)
    text = normalize_html_document(text)
    text = text.replace(_PAGE_SENTINEL, "<PAGE>")
    return text


def analyze_fast_html_page_markers(
    html: str,
    context: dict[str, Any] | None = None,
    *,
    allow_letter_number: bool = True,
) -> PageMarkerAnalysis:
    """Analyze page markers from HTML using the fast text converter."""
    if not html:
        return PageMarkerAnalysis(
            (),
            (),
            (),
            representation="html",
            source_text=html,
            terminal_state=PageMarkerTerminalState.NO_VISIBLE_LABELS,
        )
    text = convert_html_to_break_text(html)
    analysis = _analyze_ascii(
        text,
        context,
        representation="ascii",
        allow_letter_number=allow_letter_number,
    )
    return analysis


def apply_fast_html_page_policy(
    html: str,
    analysis: PageMarkerAnalysis | None = None,
    policy: PageArtifactPolicy = PageArtifactPolicy.STRIP,
    *,
    first_id: int = 1,
    context: dict[str, Any] | None = None,
    allow_letter_number: bool = True,
) -> tuple[
    str, PageMarkerAnalysis, tuple[PageBreakArtifact, ...], dict[str, dict], int
]:
    """Render fast HTML text and apply page-marker decisions."""
    text = convert_html_to_break_text(html)
    if analysis is None or analysis.representation == "html":
        analysis = _analyze_ascii(
            text,
            context,
            representation="ascii",
            allow_letter_number=allow_letter_number,
        )
    result_text, artifacts, templates, next_id = _apply_ascii_policy(
        text,
        analysis,
        policy,
        first_id=first_id,
    )
    return result_text, analysis, artifacts, templates, next_id


__all__ = [
    "analyze_fast_html_page_markers",
    "apply_fast_html_page_policy",
    "convert_html_to_break_text",
]
