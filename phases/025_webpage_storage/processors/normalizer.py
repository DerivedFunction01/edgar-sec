"""Deep document normalization and form-aware SEC content standardization."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from defs.regex import build_alternation
from defs.sec_forms.cover import (
    BoundaryInput,
    CoverBoundary,
    find_body_start,
    find_closing_span,
    find_cover_boundary_for_profile,
    find_toc_span,
    get_profile,
)
from defs.sec_forms.page_markers import (
    apply_html_page_decisions,
    enrich_html_analysis,
    refresh_html_analysis,
    strip_page_markers,
)
from defs.tables import convert_html_tables_to_ascii_v2
from defs.text.html import parse_html
from defs.text.reflow import reflow_ascii

from .forms.base import PreprocessedDocument
from .preprocessor import _RE_HTML_DISCRIMINATOR
from .router import FormRouter

_IXBRL_PREFIXES = build_alternation(["ix", "xbrli", "dei", "us-gaap"])
_RE_XML_IXBRL_TAGS = re.compile(rf"</?(?:{_IXBRL_PREFIXES}):[^>]*>", re.IGNORECASE)
_RE_TABLE_TAG = re.compile(r"<\/?table\b", re.IGNORECASE)
_RE_MULTIPLE_BLANKS = re.compile(r"\n{3,}")
_RE_TRAILING_WHITESPACE = re.compile(r"[ \t]+$", re.MULTILINE)


@dataclass(frozen=True, slots=True)
class NormalizationResult:
    """Normalized text plus structural metadata discovered during processing.

    ``cover_boundary`` is detected on the cover-healed representation while
    ``toc_span`` and ``body_start`` are resolved on the final normalized text.
    ``closing_span`` is the conservative start of the signature/exhibit tail,
    or ``None`` when no exact closing signal exists after the body.
    ``reflow`` is the ASCII span/action decision trace (empty for HTML input).
    """

    text: str
    cover_boundary: CoverBoundary
    body_start: object | None = None
    toc_span: object | None = None
    closing_span: object | None = None
    reflow: object | None = None
    page_analysis: object | None = None


class DeepNormalizer:
    """Stage 3 normalizer; coordinates generic table and form-aware structural normalization."""

    def __init__(self, router: FormRouter | None = None) -> None:
        self._router = router or FormRouter()

    def normalize(
        self,
        preprocessed: PreprocessedDocument,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        return self.normalize_result(preprocessed, metadata).text

    def normalize_result(
        self,
        preprocessed: PreprocessedDocument,
        metadata: dict[str, Any] | None = None,
    ) -> NormalizationResult:
        """Normalize preprocessed document using form-specific and generic rules."""
        form = (metadata or {}).get("form") or preprocessed.metadata.get("form")
        form_normalizer = self._router.get_normalizer(form)
        profile = get_profile(form)
        # One representation decision for the whole normalize pass so every
        # boundary call shares the same coordinate-frame declaration.
        representation = preprocessed.representation or (
            "html" if preprocessed.has_html_tags else "ascii"
        )
        is_html = representation == "html" or preprocessed.has_html_tags
        text = preprocessed.cleaned_text
        page_analysis = preprocessed.page_analysis

        # HTML node decisions are applied before any table serialization.
        # Their DOM paths are never passed to the text-span stripper.
        if is_html:
            tree = parse_html(text)
            page_analysis = enrich_html_analysis(page_analysis, tree, source_text=text)
            if apply_html_page_decisions(tree, page_analysis):
                text = str(tree)
                page_analysis = refresh_html_analysis(page_analysis, text)

        boundary = find_cover_boundary_for_profile(
            BoundaryInput(
                text,
                representation=representation,
                page_analysis=page_analysis,
            ),
            profile,
        )

        # 1. Form-specific HTML cover-page preprocessing
        if is_html and bool(_RE_TABLE_TAG.search(text)):
            cover_result = form_normalizer.preprocess_cover(
                text, metadata, page_analysis=page_analysis
            )
            text = cover_result.html
            page_analysis = refresh_html_analysis(page_analysis, text)
            boundary = find_cover_boundary_for_profile(
                BoundaryInput(
                    text,
                    representation=representation,
                    page_analysis=page_analysis,
                ),
                profile,
            )
        elif not is_html:
            boundary = find_cover_boundary_for_profile(
                BoundaryInput(
                    text,
                    representation=representation,
                    page_analysis=page_analysis,
                ),
                profile,
            )
        else:
            # HTML without tables: run cover-boundary detection even though
            # there are no layout tables to convert.
            boundary = find_cover_boundary_for_profile(
                BoundaryInput(
                    text,
                    representation=representation,
                    page_analysis=page_analysis,
                ),
                profile,
            )

        # 2. Generic HTML financial table to ASCII conversion & HTML tag stripping
        # Meant for html documents that actually are just SGML ASCII documents in the 2008-range that uses <PRE> wrappers
        if is_html and bool(_RE_HTML_DISCRIMINATOR.search(text)):
            text = convert_html_tables_to_ascii_v2(text)
            page_analysis = refresh_html_analysis(page_analysis, text)

        # 3. Invariant generic cleanup passes
        cleaned_text = _RE_XML_IXBRL_TAGS.sub("", text)
        if cleaned_text != text:
            text = cleaned_text
            if is_html:
                page_analysis = refresh_html_analysis(page_analysis, text)
        text = strip_page_markers(text, page_analysis)
        if is_html:
            page_analysis = refresh_html_analysis(page_analysis, text)

        # 4. Form-specific heading standardization
        text = form_normalizer.normalize_headers(text, metadata)

        # 5. Final whitespace cleanup
        text = _RE_TRAILING_WHITESPACE.sub("", text)
        text = _RE_MULTIPLE_BLANKS.sub("\n\n", text)
        body_start = None
        toc_span = None
        closing_span = None
        reflow_result = None
        if profile.boundary is not None and profile.body_evidence is not None:
            # Body-start analysis runs on the final normalized text; resolve
            # the TOC span on the same representation so the search lower
            # bound and TOC ineligibility use consistent line coordinates.
            toc_span = find_toc_span(
                text,
                start_line=boundary.start_line or 0,
                page_analysis=page_analysis,
                derived_taxonomy=profile.derived_taxonomy,
            )
            body_start = find_body_start(
                text,
                cover_end=boundary.end_line,
                toc_end=toc_span.end_line if toc_span is not None else None,
                evidence=profile.body_evidence,
                toc_span=toc_span,
            )
        # ASCII-only span/action pass. HTML keeps its semantic/DOM path and is
        # never hard-wrapped. Everything before the validated body anchor is
        # preserved; without an anchor no reflow happens at all.
        if (
            not is_html
            and body_start is not None
            and body_start.first_unit_line is not None
        ):
            reflow_result = reflow_ascii(
                text,
                body_start_line=body_start.first_unit_line,
                page_analysis=page_analysis,
            )
            text = reflow_result.text
        # Closing-region detection only scans after a validated body anchor;
        # without one the trailing content stays ordinary body text rather
        # than risking a premature closing cut. The reflow pass never shifts
        # lines at or before ``first_unit_line``, so the anchor remains valid
        # in the reflowed frame.
        if body_start is not None and body_start.first_unit_line is not None:
            closing_span = find_closing_span(
                text, search_from=body_start.first_unit_line + 1
            )
        return NormalizationResult(
            text=text.strip(),
            cover_boundary=boundary,
            body_start=body_start,
            toc_span=toc_span,
            closing_span=closing_span,
            reflow=reflow_result,
            page_analysis=page_analysis,
        )


__all__ = ["DeepNormalizer", "NormalizationResult"]
