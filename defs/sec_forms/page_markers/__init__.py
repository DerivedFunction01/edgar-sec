"""Public page-marker API across ASCII and future representations.

Callers use this package (or ``orchestrator``) only; representation dispatch
lives in ``orchestrator.py`` and subpackages never import each other.
"""

from .artifacts import (
    build_page_artifact_metadata,
    normalize_template_text,
    parse_page_artifact,
    parse_page_break_artifact,
    render_page_artifact,
    render_page_break_artifact,
    template_id_for,
    token_kind_for,
)
from .ascii import (
    RE_PAGE_SUFFIX,
    analyze_repeating_headers,
    apply_page_markers,
    classify_candidate,
    find_page_markers,
    is_page_marker_line,
    roman_to_int,
    strip_page_markers,
)
from .models import (
    InferredBoundary,
    PageArtifactPolicy,
    PageBreakArtifact,
    PageCandidate,
    PageMarker,
    PageMarkerAction,
    PageMarkerAnalysis,
    PageMarkerDecision,
    PageMarkerKind,
    PageMarkerSpan,
    PageMarkerTerminalState,
    PageNumberRun,
    PageRegionReport,
    TemplateEvidence,
)
from .orchestrator import (
    analyze_page_markers,
    apply_html_policy,
    apply_text_policy,
)

__all__ = [
    "RE_PAGE_SUFFIX",
    "InferredBoundary",
    "PageArtifactPolicy",
    "PageBreakArtifact",
    "PageCandidate",
    "PageMarker",
    "PageMarkerAction",
    "PageMarkerAnalysis",
    "PageMarkerDecision",
    "PageMarkerKind",
    "PageMarkerSpan",
    "PageMarkerTerminalState",
    "PageNumberRun",
    "PageRegionReport",
    "TemplateEvidence",
    "analyze_page_markers",
    "analyze_repeating_headers",
    "apply_html_policy",
    "apply_page_markers",
    "apply_text_policy",
    "build_page_artifact_metadata",
    "classify_candidate",
    "find_page_markers",
    "is_page_marker_line",
    "normalize_template_text",
    "parse_page_artifact",
    "parse_page_break_artifact",
    "render_page_artifact",
    "render_page_break_artifact",
    "roman_to_int",
    "strip_page_markers",
    "template_id_for",
    "token_kind_for",
]
