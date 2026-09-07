"""ASCII/SGML page-marker analysis and cleanup."""

from __future__ import annotations

from .candidates import (
    classify_candidate,
    roman_to_int,
)
from .headers import analyze_repeating_headers
from .orchestrator import (
    RE_PAGE_SUFFIX,
    analyze_page_markers,
    apply_page_markers,
    find_page_markers,
    is_page_marker_line,
    strip_page_markers,
)

__all__ = [
    "RE_PAGE_SUFFIX",
    "analyze_page_markers",
    "analyze_repeating_headers",
    "apply_page_markers",
    "classify_candidate",
    "find_page_markers",
    "is_page_marker_line",
    "roman_to_int",
    "strip_page_markers",
]
