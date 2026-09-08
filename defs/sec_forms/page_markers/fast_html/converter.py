"""High-throughput HTML break-to-text converter and ASCII delegation."""

from __future__ import annotations

import re
from typing import Any

from defs.regex import build_alternation
from defs.text.html import NormalizedHtmlText, normalize_html_document

from ..ascii.orchestrator import analyze_page_markers as _analyze_ascii
from ..ascii.policy import apply_page_markers as _apply_ascii_policy
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

# "SPLIT" deliberately avoids r/R: the Stage-1 glyph pass maps r/R to
# checkbox glyphs inside Wingdings/Webdings/Symbol font scopes, which would
# corrupt the sentinel (e.g. "__SEC_PAGE_B[ ]EAK_SENTINEL__").
_PAGE_SENTINEL = "__SEC_PAGE_SPLIT_SENTINEL__"


def _convert_html_to_break_text_with_metadata(html: str) -> NormalizedHtmlText:
    if not html:
        return NormalizedHtmlText("", ())
    text = _RE_PAGE_TAGS.sub(f"\n{_PAGE_SENTINEL}\n", html)
    text = _RE_HR_TAGS.sub(f"\n{_PAGE_SENTINEL}\n", text)
    text = _RE_CSS_PAGE_BREAKS.sub(f"\n{_PAGE_SENTINEL}\n", text)
    normalized = normalize_html_document(text)
    return NormalizedHtmlText(
        normalized.replace(_PAGE_SENTINEL, "\n<PAGE>\n").strip(),
        normalized.table_geometries,
    )


def convert_html_to_break_text(html: str) -> str:
    """Convert HTML to clean text stream with normalized <PAGE> sentinels."""
    if not html:
        return ""
    return _convert_html_to_break_text_with_metadata(html)


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
    text = _convert_html_to_break_text_with_metadata(html)
    analysis_context = dict(context or ())
    analysis_context["allow_table_furniture"] = True
    analysis = _analyze_ascii(
        text,
        analysis_context,
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
    str,
    PageMarkerAnalysis,
    tuple[PageBreakArtifact, ...],
    dict[str, dict],
    int,
    tuple,
]:
    """Render fast HTML text and apply page-marker decisions."""
    normalized = _convert_html_to_break_text_with_metadata(html)
    text = str(normalized)
    analysis_context = dict(context or ())
    analysis_context["allow_table_furniture"] = True
    if analysis is None or analysis.representation == "html":
        analysis = _analyze_ascii(
            text,
            analysis_context,
            representation="ascii",
            allow_letter_number=allow_letter_number,
        )
    result_text, artifacts, templates, next_id = _apply_ascii_policy(
        text,
        analysis,
        policy,
        first_id=first_id,
    )
    return (
        result_text,
        analysis,
        artifacts,
        templates,
        next_id,
        normalized.table_geometries,
    )


__all__ = [
    "analyze_fast_html_page_markers",
    "apply_fast_html_page_policy",
    "convert_html_to_break_text",
]
