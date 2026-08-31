"""Hybrid In-Place Cover Normalizer driven by a typed form-family cover profile.

The preprocessor no longer branches on form names. It receives a resolved
:class:`CoverProfile` and applies only the profile's enabled labels, boundary
phrases, and phrase-healing rules. Generic HTML cleanup, generic table
conversion, and document-wide checkbox normalization remain available to
every profile, including no-cover ones.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from bs4 import BeautifulSoup, Comment

from defs.sec_forms.cover.profiles import CoverProfile, get_profile
from defs.tables.templates import apply_table_templates
from defs.text import (
    heal_date_fragments,
    heal_split_lines,
    merge_yes_no_binary_blocks,
    normalize_checkbox_tokens,
    normalize_whitespace_and_tabs,
)


@dataclass(frozen=True, slots=True)
class CoverPreprocessResult:
    """Normalized document text produced without synthetic cover replacement."""

    html: str
    matched: bool
    template: str | None
    confidence: float
    reason: str


def _build_boundary_re(phrases: tuple[str, ...]) -> re.Pattern[str]:
    if not phrases:
        return re.compile(r"$.^", re.IGNORECASE)
    return re.compile(
        "|".join(re.escape(phrase) for phrase in phrases),
        re.IGNORECASE,
    )


def _mark_cover_candidates(
    soup: BeautifulSoup,
    profile: CoverProfile,
) -> list[object]:
    """Mark layout tables before the cover boundary for scoped conversion."""
    boundary_re = _build_boundary_re(profile.boundary_phrases)
    boundary = next((node.parent for node in soup.find_all(string=boundary_re)), None)
    tables = list(soup.find_all("table"))
    if boundary is not None:
        previous = set(boundary.find_all_previous("table"))
        candidates = [table for table in tables if table in previous]
    else:
        labels = profile.labels
        evidence = profile.evidence_terms
        candidates = [
            table
            for table in tables
            if any(term in table.get_text(" ", strip=True).lower() for term in labels)
            or any(term in table.get_text(" ", strip=True).lower() for term in evidence)
            or table.find_previous(
                string=re.compile(r"section\s+12\(b\)", re.IGNORECASE)
            )
        ]

    for table in candidates:
        table["data-cover-candidate"] = "true"
    return candidates


def _find_cover_end_line(lines: list[str], boundary_re: re.Pattern[str]) -> int | None:
    """Return the index of the first line that ends the cover region.

    The cover region is every line before the first high-confidence boundary
    phrase. Body content after that line is not subject to cover-specific
    text healing, which prevents overhealing financial statements and other
    body prose that merely resembles cover captions.
    """
    for index, line in enumerate(lines):
        if boundary_re.search(line):
            return index
    return None


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
            )

        soup = BeautifulSoup(html_text, "lxml")

        # 1. Clean non-displaying and hidden XBRL header tags
        for el in soup(
            ["head", "script", "style", "meta", "noscript", "ix:hidden", "ix:header"]
        ):
            el.decompose()
        for comment in soup.find_all(string=lambda value: isinstance(value, Comment)):
            comment.extract()

        # 2. In-place layout table transformation, gated by profile eligibility.
        boundary_re = _build_boundary_re(self.profile.boundary_phrases)
        candidates: list[object] = []
        if self.profile.eligible:
            candidates = _mark_cover_candidates(soup, self.profile)
            for table in list(soup.find_all("table")):
                if table not in candidates:
                    continue
                source_grid = span_grid(table, with_spans=False)
                if source_grid:
                    template_result = apply_table_templates(
                        table,
                        source_grid,
                        scope=self.profile.table_scope,
                    )
                    if template_result is not None:
                        table.replace_with(
                            soup.new_string(f"\n\n{template_result.text}\n\n")
                        )
                        continue

        # 3. Convert remaining body/data tables through the generic renderer.
        converted_html = convert_html_tables_to_ascii(str(soup))
        table_blocks: list[str] = []

        def protect_table(match: re.Match[str]) -> str:
            table_blocks.append(match.group(0))
            return f"__CANONICAL_TABLE_{len(table_blocks) - 1}__"

        raw_text = re.sub(
            r"<TABLE>.*?</TABLE>", protect_table, converted_html, flags=re.DOTALL
        )

        # 4. Normalize whitespace, tabs, and checkbox symbols.
        # Checkbox glyph canonicalization is benign and applies document-wide.
        normalized_text = normalize_whitespace_and_tabs(raw_text)
        normalized_text = normalize_checkbox_tokens(normalized_text)

        # 5. Apply cover-specific healing only before the cover boundary so
        # body content (financial statements, notes, exhibits) is not
        # overhealed. Profiles with no enabled rules or boundaries skip this.
        raw_lines = normalized_text.splitlines()
        cover_end = _find_cover_end_line(raw_lines, boundary_re)
        if cover_end is None:
            cover_lines = raw_lines
            body_lines: list[str] = []
        else:
            cover_lines = raw_lines[:cover_end]
            body_lines = raw_lines[cover_end:]

        if self.profile.eligible and self.profile.phrase_rules:
            cover_lines = merge_yes_no_binary_blocks(cover_lines)
            cover_lines = heal_split_lines(
                cover_lines, rules=tuple(self.profile.phrase_rules)
            )
            cover_lines = heal_date_fragments(cover_lines)

        final_text = "\n".join(cover_lines + body_lines)
        for index, table_block in enumerate(table_blocks):
            final_text = final_text.replace(f"__CANONICAL_TABLE_{index}__", table_block)

        matched = bool(self.profile.eligible and candidates)
        return CoverPreprocessResult(
            html=final_text,
            matched=matched,
            template="hybrid_in_place_cover_preprocessor" if matched else None,
            confidence=0.99 if matched else 0.0,
            reason="success" if matched else "no_cover_profile_or_evidence",
        )


def span_grid(table: object, *, with_spans: bool = False):
    """Re-exported for local use to avoid a top-level circular import."""
    from defs.tables import span_grid as _span_grid

    return _span_grid(table, with_spans=with_spans)


def convert_html_tables_to_ascii(html_content: str) -> str:
    """Re-exported for local use to avoid a top-level circular import."""
    from defs.tables import convert_html_tables_to_ascii as _convert

    return _convert(html_content)


__all__ = ["CoverPreprocessResult", "HybridCoverPreprocessor"]
