"""The composition seam: one ordered normalization chain over a raw payload.

Every engine stage already exists as a pure function; nothing composed them.
This module owns the *only* place the stage order is written, which is the
load-bearing invariant: reflow must never run before table protection, and the
cover boundary must be detected on the same coordinate frame the checkmark
rewriter edits.

Stage order (each step is a pure function of the previous text):

1. ``unpack``      SGML bundle / primary sub-document selection
2. ``html_clean``  tag decomposition, which masks tagged tables internally
3. ``page_policy`` validated page-furniture removal
4. ``boundary``    cover region detection (form-scoped signals)
5. ``checkmark``   yes/no pair normalization + constraint solve + rewrite
6. ``content``     per-form content hook
7. ``whitespace``  final line/bullet/blank-run normalization
8. ``body_start``  structural body anchor after the cover
9. ``reflow``      ASCII block reflow, with all line anchors remapped
10. ``closing``    signature / closing tail span

Departures from v1's ``ProfileDrivenPipeline`` are deliberate and narrow:

* v1 resolved page markers on the HTML DOM via ``apply_html_policy``. v2 has no
  HTML-frame page-marker path, so markers are resolved on the *rendered text*
  frame for both representations. Documented rather than silently narrowed.
* v1 had a per-family pipeline class. v2 keeps one chain and reads per-form data
  from a plugin, so the order below is the single source of truth.
* v1's TOC span is not ported (no v2 TOC finder exists), so body-start detection
  is anchored on cover end alone.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from edgar_sec.engine.document.html import normalize_html_document
from edgar_sec.engine.document.html_breaks import (
    convert_sentinels_to_page_markers,
    insert_page_sentinels,
)
from edgar_sec.engine.document.page_markers import (
    PageArtifactPolicy,
    PageMarkerAnalysis,
    apply_text_policy,
)
from edgar_sec.engine.document.unpacker import (
    extract_target_sub_document,
    has_sgml_documents,
)
from edgar_sec.engine.document.whitespace import (
    count_lines,
    normalize_final_text_whitespace,
)
from edgar_sec.engine.forms.checkmarks._yesno import normalize_yes_no_pair_line
from edgar_sec.engine.forms.checkmarks.rewrite import (
    apply_cover_checkmark_decisions,
    update_table_geometries,
)
from edgar_sec.engine.forms.checkmarks.solver import (
    CoverCheckmarkResult,
    infer_cover_checkmarks,
)
from edgar_sec.engine.forms.cover.body_start import find_body_start
from edgar_sec.engine.forms.cover.boundary import find_cover_boundary
from edgar_sec.engine.forms.cover.closing import ClosingSpan, find_closing_span
from edgar_sec.engine.forms.cover.healing import heal_cover_text
from edgar_sec.engine.forms.cover.models import (
    BodyStart,
    CoverBoundary,
)
from edgar_sec.engine.forms.cover.reflow import (
    is_checkbox_answer_line,
    is_cover_layout_line,
    is_page_marker_line,
)
from edgar_sec.engine.forms.cover.tables import clean_cover_tables
from edgar_sec.engine.forms.plugins.models import FormPlugin
from edgar_sec.engine.forms.plugins.registry import get_plugin
from edgar_sec.engine.reflow.engine import reflow_ascii
from edgar_sec.engine.reflow.types import ReflowPolicy, ReflowResult, build_line_mapper
from edgar_sec.foundation.hashing import sha256_text

_REPRESENTATION_HTML = "html"
_REPRESENTATION_ASCII = "ascii"


@dataclass(frozen=True, slots=True)
class NormalizationResult:
    """Normalized text plus the structural facts discovered while producing it.

    ``cover_boundary`` is detected on the healed representation; ``body_start``
    and ``closing_span`` are resolved on the final normalized text. ``reflow``
    is the ASCII block decision trace and is empty for HTML input.
    ``stage_trace`` records bounded per-stage diagnostics: text identity, line
    and character counts, so a regression can be localized to one stage without
    re-running the pipeline.
    """

    text: str
    representation: str
    cover_boundary: CoverBoundary
    body_start: BodyStart | None = None
    closing_span: ClosingSpan | None = None
    reflow: ReflowResult | None = None
    page_analysis: PageMarkerAnalysis | None = None
    table_geometries: tuple = ()
    checkmark_inference: CoverCheckmarkResult | None = None
    family: str = ""
    stage_trace: tuple[dict[str, Any], ...] = ()
    #: The exclusive cover end as detected, *before* reflow renumbered lines.
    #: ``cover_boundary.end_line`` is reported in the final text's coordinates,
    #: which reflow can shift; a line that reflow collapsed into a longer line
    #: cannot be mapped back, so this is the only stable line number. It is also
    #: the frame the checkmark solver actually ran against.
    cover_boundary_detected_line: int | None = None
    #: The inclusive cover start as detected, before reflow.
    cover_start_detected_line: int | None = None

    @property
    def is_html(self) -> bool:
        return self.representation == _REPRESENTATION_HTML


class _StageTracer:
    """Accumulates per-stage identity/count diagnostics without re-hashing text.

    The identity of a stage is only recomputed when the text object actually
    changed, so an unchanged stage costs a comparison rather than a full digest.
    """

    __slots__ = ("_cached_identity", "_cached_lines", "_cached_text", "_trace")

    def __init__(self, text: str) -> None:
        self._cached_text = text
        self._cached_identity = sha256_text(text)
        self._cached_lines = count_lines(text)
        self._trace: list[dict[str, Any]] = []

    def record(self, stage: str, text: str, **extra: Any) -> str:
        if text is not self._cached_text and text != self._cached_text:
            self._cached_text = text
            self._cached_identity = sha256_text(text)
            self._cached_lines = count_lines(text)
        self._trace.append(
            {
                "stage": stage,
                "text_identity": self._cached_identity,
                "line_count": self._cached_lines,
                "char_count": len(text),
                **extra,
            }
        )
        return text

    @property
    def trace(self) -> tuple[dict[str, Any], ...]:
        return tuple(self._trace)


def _unpack(
    payload: str | bytes,
    *,
    target_types: tuple[str, ...] | None,
    primary_filename: str | None,
) -> tuple[str, str]:
    """Stage 1: select the primary document text and its representation."""
    if isinstance(payload, (bytes, bytearray, memoryview)):
        raw = bytes(payload)
        if has_sgml_documents(raw):
            extracted = extract_target_sub_document(
                raw, target_types=target_types, primary_filename=primary_filename
            )
            if extracted is not None:
                payload = extracted
                raw = extracted
        else:
            payload = raw
    if isinstance(payload, bytes):
        for enc in ("utf-8", "cp1252", "latin-1"):
            try:
                text = payload.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            text = payload.decode("latin-1", errors="replace")
    else:
        text = payload
    if not text:
        return "", _REPRESENTATION_ASCII
    head = text[:65536].lower()
    lowered_filename = primary_filename.lower() if primary_filename else ""
    is_html = (
        lowered_filename.endswith((".htm", ".html", ".xhtml"))
        or "<html" in head
        or "<!doctype html" in head
        or "<body" in head
    )
    return text, (_REPRESENTATION_HTML if is_html else _REPRESENTATION_ASCII)


def _html_clean(text: str) -> str:
    """Stage 2: decompose tags. Tagged tables are masked and restored internally."""
    return str(normalize_html_document(text))


def _normalize_yes_no_pairs(text: str, boundary: CoverBoundary) -> tuple[str, bool]:
    """Collapse bare yes/no glyph pairs inside the cover region only."""
    if boundary.end_line is None:
        return text, False
    lines = text.split("\n")
    start = boundary.start_line or 0
    end = min(boundary.end_line, len(lines))
    if start >= end:
        return text, False
    changed = False
    for index in range(start, end):
        normalized = normalize_yes_no_pair_line(lines[index])
        if normalized != lines[index]:
            lines[index] = normalized
            changed = True
    if not changed:
        return text, False
    return "\n".join(lines), True


def _reflow_policy() -> ReflowPolicy:
    """The reflow policy used for every ASCII filing body."""
    return ReflowPolicy(
        unwrap_pre_body_prose=True,
        relax_prose_layout_gaps=True,
        unwrap_bullet_continuations=True,
        is_checkbox_answer_line=is_checkbox_answer_line,
        is_page_boundary_line=is_page_marker_line,
        is_structural_line=is_cover_layout_line,
    )


class DocumentNormalizer:
    """Runs the shared normalization chain for one form family."""

    __slots__ = ("_plugin", "tag_untagged_tables")

    def __init__(
        self,
        plugin: FormPlugin | None = None,
        *,
        form: str | None = None,
        tag_untagged_tables: bool = True,
    ) -> None:
        self._plugin = plugin if plugin is not None else get_plugin(form)
        self.tag_untagged_tables = tag_untagged_tables

    @property
    def plugin(self) -> FormPlugin:
        return self._plugin

    def normalize(
        self,
        payload: str | bytes,
        *,
        target_types: tuple[str, ...] | None = None,
        primary_filename: str | None = None,
        page_artifact_policy: PageArtifactPolicy = PageArtifactPolicy.STRIP,
    ) -> NormalizationResult:
        """Run every stage in order and return the discovered structure."""
        text, representation = _unpack(
            payload,
            target_types=target_types,
            primary_filename=primary_filename,
        )
        tracer = _StageTracer(text)
        tracer.record("unpacked", text, representation=representation)

        is_html = representation == _REPRESENTATION_HTML
        table_geometries: tuple = ()
        if is_html:
            break_html = insert_page_sentinels(text)
            normalized = normalize_html_document(break_html)
            text = tracer.record(
                "html_cleaned", convert_sentinels_to_page_markers(str(normalized))
            )
            table_geometries = normalized.table_geometries
            text, page_analysis, _artifacts, _templates, _next_id = apply_text_policy(
                text, None, page_artifact_policy, representation="html"
            )
            tracer.record("page_policy", text, marker_count=len(page_analysis.markers))
        else:
            text, page_analysis, _artifacts, _templates, _next_id = apply_text_policy(
                text, None, page_artifact_policy, representation=representation
            )
            tracer.record("page_policy", text, marker_count=len(page_analysis.markers))

        boundary = find_cover_boundary(
            text,
            representation=representation,
            page_analysis=page_analysis,
            signals=self._plugin.boundary_signals,
        )
        detected_end_line = boundary.end_line
        detected_start_line = boundary.start_line
        tracer.record("cover_boundary", text, method=str(boundary.method))

        text, pair_changed = _normalize_yes_no_pairs(text, boundary)
        if pair_changed:
            tracer.record("after_yes_no_pairs", text)

        checkmark_inference: CoverCheckmarkResult | None = None
        if self._plugin.cover_schema is not None:
            checkmark_inference = infer_cover_checkmarks(
                text,
                boundary,
                family=self._plugin.family,
                table_geometries=table_geometries,
                schema=self._plugin.cover_schema,
            )
            if checkmark_inference.decisions:
                text, checkmark_changed, unwrapped = apply_cover_checkmark_decisions(
                    text, checkmark_inference
                )
                table_geometries = update_table_geometries(
                    table_geometries, checkmark_inference, unwrapped
                )
                if checkmark_changed:
                    tracer.record("after_checkmark_rewrite", text)

        if self._plugin.transform_content is not None:
            text = self._plugin.transform_content(text)
            tracer.record("after_form_content", text)

        if boundary.end_line is not None and "<TABLE>" in text:
            cleaned_cover_text, table_geometries = clean_cover_tables(
                text,
                boundary,
                table_geometries=table_geometries,
                enabled_cleaners=("report_period",),
            )
            if cleaned_cover_text != text:
                text = tracer.record("after_cover_table_cleaning", cleaned_cover_text)

        healing_rules = getattr(self._plugin, "healing_rules", ())
        text, cover_healed = heal_cover_text(
            text,
            boundary,
            healing_rules=healing_rules,
            merge_binary_blocks=is_html,
            reflow_prose=False,
        )
        if cover_healed:
            tracer.record("after_cover_healing", text)

        text = tracer.record(
            "after_final_whitespace", normalize_final_text_whitespace(text)
        )

        body_start: BodyStart | None = None
        if self._plugin.enable_body_start and boundary.end_line is not None:
            body_start = find_body_start(
                text,
                cover_end=boundary.end_line,
                evidence=self._plugin.boundary_signals,
            )

        body_start_line = _effective_body_start_line(boundary, body_start)
        reflow_result: ReflowResult | None = None
        if not is_html and body_start_line > 0:
            tracer.record("before_reflow", text)
            policy = _reflow_policy()
            policy = replace(policy, tag_untagged_tables=self.tag_untagged_tables)
            reflow_result = reflow_ascii(
                text,
                body_start_line=body_start_line,
                page_analysis=page_analysis,
                policy=policy,
            )
            text = reflow_result.text
            boundary, body_start = _remap_line_anchors(
                boundary, body_start, build_line_mapper(reflow_result.decisions)
            )
            tracer.record("after_reflow", text)

        closing_span: ClosingSpan | None = None
        if body_start is not None and body_start.first_unit_line is not None:
            closing_span = find_closing_span(
                text, search_from=body_start.first_unit_line + 1
            )

        return NormalizationResult(
            text=text.strip(),
            representation=representation,
            cover_boundary=boundary,
            body_start=body_start,
            closing_span=closing_span,
            reflow=reflow_result,
            page_analysis=page_analysis,
            table_geometries=_serialize_table_geometries(table_geometries),
            checkmark_inference=checkmark_inference,
            family=self._plugin.family,
            stage_trace=tracer.trace,
            cover_boundary_detected_line=detected_end_line,
            cover_start_detected_line=detected_start_line,
        )


def _serialize_table_geometries(
    geometries: Any,
) -> tuple[dict[str, Any], ...]:
    serialized: list[dict[str, Any]] = []
    for g in geometries:
        if hasattr(g, "table_index"):
            serialized.append(
                {
                    "table_index": g.table_index,
                    "confidence": getattr(g, "confidence", 1.0),
                    "diagnostics": list(getattr(g, "diagnostics", ())),
                    "is_fallback_to_legacy": getattr(g, "is_fallback_to_legacy", False),
                    "row_count": len(getattr(g, "rows", ())),
                }
            )
        elif isinstance(g, dict):
            serialized.append(g)
    return tuple(serialized)


def _effective_body_start_line(
    boundary: CoverBoundary, body_start: BodyStart | None
) -> int:
    """The first line the reflow cascade is allowed to treat as body prose."""
    if body_start is not None and body_start.first_unit_line is not None:
        return body_start.first_unit_line
    return boundary.end_line or 0


def _remap_line_anchors(
    boundary: CoverBoundary,
    body_start: BodyStart | None,
    map_line: Any,
) -> tuple[CoverBoundary, BodyStart | None]:
    """Translate every detected line anchor into post-reflow coordinates."""
    remapped = boundary
    if boundary.end_line is not None:
        remapped = replace(remapped, end_line=map_line(boundary.end_line))
    if boundary.start_line is not None:
        remapped = replace(remapped, start_line=map_line(boundary.start_line))
    if body_start is None:
        return remapped, None
    updated = body_start
    if body_start.line is not None:
        updated = replace(updated, line=map_line(body_start.line))
    if body_start.heading_line is not None:
        updated = replace(updated, heading_line=map_line(body_start.heading_line))
    if body_start.first_unit_line is not None:
        updated = replace(updated, first_unit_line=map_line(body_start.first_unit_line))
    return remapped, updated


def normalize_document(
    payload: str | bytes,
    *,
    form: str | None = None,
    plugin: FormPlugin | None = None,
    target_types: tuple[str, ...] | None = None,
    primary_filename: str | None = None,
    page_artifact_policy: PageArtifactPolicy = PageArtifactPolicy.STRIP,
    tag_untagged_tables: bool = True,
) -> NormalizationResult:
    """Normalize a raw filing payload through the shared chain for its form.

    This is the single entry point the storage pipeline and the review tool both
    call; there is no per-form pipeline class to choose between.
    """
    normalizer = DocumentNormalizer(
        plugin,
        form=form,
        tag_untagged_tables=tag_untagged_tables,
    )
    return normalizer.normalize(
        payload,
        target_types=target_types,
        primary_filename=primary_filename,
        page_artifact_policy=page_artifact_policy,
    )


__all__ = [
    "DocumentNormalizer",
    "NormalizationResult",
    "normalize_document",
]
