"""Hybrid In-Place Cover Normalizer driven by a typed form-family cover profile.

The preprocessor no longer branches on form names. It receives a resolved
:class:`CoverProfile` and applies only the profile's enabled labels, boundary
evidence, and phrase-healing rules. Cover termination is selected by the shared
:class:`defs.sec_forms.cover.find_cover_boundary` detector, which returns a
typed :class:`CoverBoundary` consumed by later TOC/body stages. Generic HTML
cleanup, generic table conversion, and document-wide checkbox normalization
remain available to every profile, including no-cover ones.
"""

from __future__ import annotations

from typing import Any

from defs.sec_forms.cover import BoundaryInput, find_cover_boundary_for_profile
from defs.sec_forms.cover.profiles import CoverProfile, get_profile
from defs.sec_forms.page_markers import PageMarkerAnalysis, analyze_page_markers
from defs.tables.protection import mask_tagged_tables, restore_tagged_tables
from defs.text import (
    heal_date_fragments,
    heal_split_lines,
    merge_yes_no_binary_blocks,
    normalize_checkbox_tokens,
    normalize_whitespace_and_tabs,
)
from defs.text.html import FastHtmlNode, FastHtmlTree, parse_html

from ..base import CoverPreprocessResult


def _mark_cover_candidates(
    tree: FastHtmlTree,
    profile: CoverProfile,
) -> list[FastHtmlNode]:
    """Mark layout tables before the cover boundary for scoped conversion."""
    tables = tree.css("table")
    labels = profile.labels
    evidence = profile.evidence_terms
    candidates: list[FastHtmlNode] = []
    for table in tables:
        text = table.text().lower()
        if (
            any(term in text for term in labels)
            or any(term in text for term in evidence)
            or "section 12(b)" in text
        ):
            candidates.append(table)
    return candidates


class HybridCoverPreprocessor:
    """In-place DOM cover preprocessor driven by a typed form-family profile.

    The preprocessor preserves 100% of organic filing prose while decomposing
    layout tables and healing split multi-line phrases. Behavior is scoped by
    the supplied :class:`CoverProfile`; a missing or generic profile degrades
    to no-cover processing.
    """

    def __init__(self, profile: CoverProfile | str | None = None) -> None:
        if isinstance(profile, CoverProfile):
            self.profile = profile
        else:
            # Preserve backward compatibility: callers that omit a profile get
            # the annual 10-K profile. Explicit no-cover profiles are opt-in.
            self.profile = get_profile(profile or "10-K")

    def preprocess(
        self,
        html_text: str,
        company_name: str = "",
        metadata: dict[str, Any] | None = None,
        page_analysis: PageMarkerAnalysis | None = None,
    ) -> CoverPreprocessResult:
        _ = company_name
        _ = metadata
        if not html_text or "<html" not in html_text.lower():
            return CoverPreprocessResult(
                html=html_text,
                matched=False,
                template=None,
                confidence=0.0,
                reason="non_html_text",
                cover_boundary=find_cover_boundary_for_profile(
                    BoundaryInput(
                        html_text,
                        representation="html",
                        page_analysis=page_analysis,
                    ),
                    get_profile("GENERIC"),
                ),
            )

        tree = parse_html(html_text)

        # 1. Clean non-displaying and hidden XBRL header tags
        tree.strip_tags(
            ("head", "script", "style", "meta", "noscript", "ix:hidden", "ix:header")
        )

        # 2. Classify cover candidates without applying a formatter. All tables
        # use the geometry-first renderer below so cover and body output share
        # one alignment and unwrapping policy.
        candidates: list[FastHtmlNode] = []
        if self.profile.boundary is not None:
            candidates = _mark_cover_candidates(tree, self.profile)

        # 3. Convert all tables through the geometry-first renderer.
        converted_html = normalize_checkbox_tokens(
            convert_html_tables_to_ascii(str(tree))
        )
        boundary_source = normalize_whitespace_and_tabs(converted_html)
        boundary_analysis = page_analysis
        if (
            boundary_analysis is None
            or boundary_analysis.source_text != boundary_source
        ):
            # Table conversion and whitespace normalization create a new text
            # frame. Re-detect text markers instead of carrying stale offsets.
            boundary_analysis = analyze_page_markers(
                boundary_source, representation="html"
            )
        boundary = find_cover_boundary_for_profile(
            BoundaryInput(
                boundary_source,
                representation="html",
                page_analysis=boundary_analysis,
            ),
            self.profile,
        )

        masked_text, table_spans = mask_tagged_tables(converted_html)

        # 4. Normalize whitespace, tabs, and checkbox symbols.
        # Checkbox glyph canonicalization is benign and applies document-wide.
        normalized_text = normalize_whitespace_and_tabs(masked_text)
        normalized_text = normalize_checkbox_tokens(normalized_text)

        # 5. Apply cover-specific healing only before the cover boundary so
        # body content (financial statements, notes, exhibits) is not
        # overhealed. Profiles with no enabled rules or boundaries skip this.
        raw_lines = normalized_text.splitlines()
        if boundary.end_line is None:
            cover_lines = []
            body_lines = raw_lines
        else:
            cover_lines = raw_lines[: boundary.end_line]
            body_lines = raw_lines[boundary.end_line :]

        if boundary.end_line is not None and self.profile.healing_rules:
            cover_lines = merge_yes_no_binary_blocks(cover_lines)
            cover_lines = heal_split_lines(
                cover_lines, rules=tuple(self.profile.healing_rules)
            )
            cover_lines = heal_date_fragments(cover_lines)

        final_text = "\n".join(cover_lines + body_lines)
        if table_spans:
            final_text = restore_tagged_tables(final_text, table_spans)

        matched = bool(self.profile.boundary is not None and candidates)
        return CoverPreprocessResult(
            html=final_text,
            matched=matched,
            template="hybrid_in_place_cover_preprocessor" if matched else None,
            confidence=boundary.confidence if matched else 0.0,
            reason="success" if matched else "no_cover_profile_or_evidence",
            cover_boundary=boundary,
        )


def convert_html_tables_to_ascii(html_content: str) -> str:
    """Re-exported for local use to avoid a top-level circular import."""
    from defs.tables import convert_html_tables_to_ascii as _convert

    return _convert(html_content)


__all__ = ["CoverPreprocessResult", "HybridCoverPreprocessor"]
