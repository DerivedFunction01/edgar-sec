"""Public page-marker API across ASCII and future representations."""

from .ascii import (
    RE_PAGE_SUFFIX,
    analyze_page_markers,
    classify_candidate,
    find_page_markers,
    is_page_marker_line,
    roman_to_int,
    strip_page_markers,
)
from .html import (
    apply_html_page_decisions,
    enrich_html_analysis,
    refresh_html_analysis,
)
from .models import (
    InferredBoundary,
    PageCandidate,
    PageMarker,
    PageMarkerAction,
    PageMarkerAnalysis,
    PageMarkerDecision,
    PageMarkerKind,
    PageMarkerSpan,
    PageMarkerTerminalState,
    PageNumberRun,
    TemplateEvidence,
)
from .pre import extract_ascii_pre

__all__ = [
    "RE_PAGE_SUFFIX",
    "InferredBoundary",
    "PageCandidate",
    "PageMarker",
    "PageMarkerAction",
    "PageMarkerAnalysis",
    "PageMarkerDecision",
    "PageMarkerKind",
    "PageMarkerSpan",
    "PageMarkerTerminalState",
    "PageNumberRun",
    "TemplateEvidence",
    "analyze_page_markers",
    "apply_html_page_decisions",
    "classify_candidate",
    "enrich_html_analysis",
    "extract_ascii_pre",
    "find_page_markers",
    "is_page_marker_line",
    "refresh_html_analysis",
    "roman_to_int",
    "strip_page_markers",
]
