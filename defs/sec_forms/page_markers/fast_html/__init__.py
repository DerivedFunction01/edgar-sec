"""High-throughput HTML break-to-text and page marker subpackage."""

from __future__ import annotations

from .converter import (
    analyze_fast_html_page_markers,
    apply_fast_html_page_policy,
    convert_html_to_break_text,
)

__all__ = [
    "analyze_fast_html_page_markers",
    "apply_fast_html_page_policy",
    "convert_html_to_break_text",
]
