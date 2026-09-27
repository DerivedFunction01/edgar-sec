"""Async document processor protocol, execution runner, and DefaultFilingProcessor."""

from __future__ import annotations

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from defs.sec_documents import DocumentPreprocessor
from defs.sec_forms.forms.evaluator import get_evaluator
from defs.sec_forms.normalization import DocumentNormalizer, NormalizationResult
from defs.sec_forms.page_markers import PageArtifactPolicy
from defs.text import count_words

from .schemas import DocumentLocator, detect_mime, doc_id

_thread_local = threading.local()


def _get_thread_loop() -> asyncio.AbstractEventLoop:
    loop = getattr(_thread_local, "loop", None)
    if loop is None or loop.is_closed():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        _thread_local.loop = loop
    return loop


@dataclass(frozen=True, slots=True)
class ProcessedDocument:
    """Outcome of processing one raw filing document through an async pipeline."""

    doc_id: str
    payload: bytes
    byte_size: int
    mime_type: str
    metadata: dict[str, object] = field(default_factory=dict)
    processor_fingerprint: str = "custom:unspecified"
    representation: str = "application/octet-stream"


@runtime_checkable
class DocumentProcessor(Protocol):
    """Async pipeline processor for transforming, cleaning, and extracting documents."""

    async def process(
        self, raw_bytes: bytes, locator: DocumentLocator
    ) -> ProcessedDocument:
        """Asynchronously process raw bytes for a given locator."""
        ...


class NoOpDocumentProcessor:
    """Default async pass-through document processor."""

    async def process(
        self, raw_bytes: bytes, locator: DocumentLocator
    ) -> ProcessedDocument:
        return ProcessedDocument(
            doc_id=doc_id(locator.accession, locator.document_path),
            payload=raw_bytes,
            byte_size=len(raw_bytes),
            mime_type=detect_mime(locator.document_path),
            metadata={},
            processor_fingerprint="raw-pass-through",
            representation="raw",
        )


def execute_processor(
    processor: DocumentProcessor,
    raw_bytes: bytes,
    locator: DocumentLocator,
) -> ProcessedDocument:
    """Execute an async DocumentProcessor from synchronous worker threads reusing thread event loops."""
    coro = processor.process(raw_bytes, locator)
    try:
        current_loop = asyncio.get_running_loop()
    except RuntimeError:
        current_loop = None

    if current_loop is not None and current_loop.is_running():
        with ThreadPoolExecutor() as pool:
            return pool.submit(_get_thread_loop().run_until_complete, coro).result()
    return _get_thread_loop().run_until_complete(coro)


class DefaultFilingProcessor(DocumentProcessor):
    """Default end-to-end filing processor delegating preprocessing & normalization to defs."""

    processor_fingerprint = "default-filing-processor:v3"
    representation = "normalized-text"

    def __init__(
        self,
        preprocessor: DocumentPreprocessor | None = None,
        normalizer: DocumentNormalizer | None = None,
        page_artifact_policy: PageArtifactPolicy = PageArtifactPolicy.STRIP,
        *,
        tag_untagged_tables: bool = False,
    ) -> None:
        self.preprocessor = preprocessor or DocumentPreprocessor()
        self.normalizer = normalizer or DocumentNormalizer(
            tag_untagged_tables=tag_untagged_tables
        )
        self.page_artifact_policy = page_artifact_policy

    def build_processed_document(
        self,
        preprocessed: object,
        normalization: NormalizationResult,
        locator: DocumentLocator,
    ) -> ProcessedDocument:
        """Construct canonical ProcessedDocument from completed preprocessing and normalization."""
        evaluator = get_evaluator(locator.form)
        decision = evaluator.evaluate(preprocessed, locator)
        normalized_text = normalization.text
        output_payload = normalized_text.encode("utf-8")

        cover_boundary = normalization.cover_boundary
        body = normalization.body_start
        toc = normalization.toc_span
        closing = normalization.closing_span
        reflow = normalization.reflow
        reflow_counts: dict[str, int] = {}
        if reflow is not None:
            for span_decision in getattr(reflow, "decisions", ()):
                reflow_counts[span_decision.action] = (
                    reflow_counts.get(span_decision.action, 0) + 1
                )
        page_analysis = normalization.page_analysis
        page_decisions = (
            getattr(page_analysis, "decisions", ()) if page_analysis is not None else ()
        )
        meta = {
            "is_stub": decision.is_stub,
            "category": decision.category,
            "decision_action": decision.action.value,
            "decision_reason": decision.reason,
            "target_exhibit": decision.target_exhibit,
            "detected_encoding": getattr(preprocessed, "detected_encoding", "utf-8"),
            "word_count": count_words(normalized_text),
            "cover_boundary_method": cover_boundary.method.value
            if cover_boundary
            else "none",
            "cover_boundary_line": cover_boundary.end_line if cover_boundary else None,
            "cover_boundary_confidence": cover_boundary.confidence
            if cover_boundary
            else 0.0,
            "cover_boundary_start_line": cover_boundary.start_line
            if cover_boundary
            else None,
            "toc_start_line": toc.start_line if toc is not None else None,
            "toc_end_line": toc.end_line if toc is not None else None,
            "body_start_line": getattr(body, "line", None),
            "body_heading_line": getattr(body, "heading_line", None),
            "body_first_unit_line": getattr(body, "first_unit_line", None),
            "body_anchor_type": getattr(body, "anchor_type", None),
            "body_confidence": getattr(body, "confidence", None),
            "body_delayed": getattr(body, "delayed", None),
            "body_rejection_reasons": list(
                getattr(body, "rejection_reasons", ()) or ()
            ),
            "closing_start_line": getattr(closing, "start_line", None),
            "closing_kind": getattr(closing, "kind", None),
            "closing_confidence": getattr(closing, "confidence", None),
            "reflow_unwrap_blocks": reflow_counts.get("unwrap", 0),
            "reflow_preserve_blocks": reflow_counts.get("preserve", 0),
            "reflow_tag_blocks": reflow_counts.get("tag_and_preserve", 0),
            "page_marker_count": len(getattr(page_analysis, "markers", ()))
            if page_analysis
            else 0,
            "page_marker_removed_count": sum(
                getattr(dec, "action", None) is not None
                and getattr(dec.action, "value", None) == "remove"
                for dec in page_decisions
            ),
            "page_marker_normalized_count": sum(
                getattr(dec, "action", None) is not None
                and getattr(dec.action, "value", None) == "normalize"
                for dec in page_decisions
            ),
            "page_marker_preserved_count": sum(
                getattr(dec, "action", None) is not None
                and getattr(dec.action, "value", None) == "preserve"
                for dec in page_decisions
            ),
            "page_marker_run_count": len(getattr(page_analysis, "page_number_runs", ()))
            if page_analysis
            else 0,
            "page_marker_accepted_runs": (
                [
                    {
                        "family": run.family,
                        "namespace": run.namespace,
                        "candidate_count": len(run.candidates),
                        "monotone_fraction": run.monotone_fraction,
                        "alignment_fraction": run.alignment_fraction,
                        "source_start_line": run.source_start_line,
                        "source_end_line": run.source_end_line,
                        "strategy": run.strategy,
                    }
                    for run in getattr(page_analysis, "page_number_runs", ())[:64]
                ]
                if page_analysis
                else []
            ),
            "page_marker_inferred_boundary_count": len(
                getattr(page_analysis, "inferred_boundaries", ())
            )
            if page_analysis
            else 0,
            "page_marker_terminal_state": (
                page_analysis.terminal_state.value if page_analysis else "none"
            ),
            "page_marker_no_visible_labels": (
                page_analysis.terminal_state.value == "no_visible_labels"
                if page_analysis
                else False
            ),
            "page_marker_unresolved_count": len(
                getattr(page_analysis, "unresolved", ())
            )
            if page_analysis
            else 0,
            "page_artifacts": normalization.page_artifacts,
        }

        return ProcessedDocument(
            doc_id=doc_id(locator.accession, locator.document_path),
            payload=output_payload,
            byte_size=len(output_payload),
            mime_type="text/plain",
            metadata=meta,
            processor_fingerprint=self.processor_fingerprint,
            representation=self.representation,
        )

    async def process(
        self,
        raw_bytes: bytes,
        locator: DocumentLocator,
    ) -> ProcessedDocument:
        """Process raw filing bytes through the normalization pipeline."""
        metadata = {"form": locator.form}
        filing_year = getattr(locator, "filing_year", None)
        if filing_year is not None:
            metadata["filing_year"] = filing_year

        # Stage 1: Generic Preprocessing (in defs.sec_documents)
        preprocessed = self.preprocessor.preprocess(raw_bytes, metadata=metadata)

        # Stage 2: Form-driven Normalization (in defs.sec_forms.normalization)
        normalization = self.normalizer.normalize_result(
            preprocessed,
            metadata={"form": locator.form},
            page_artifact_policy=self.page_artifact_policy,
        )

        return self.build_processed_document(preprocessed, normalization, locator)


__all__ = [
    "DefaultFilingProcessor",
    "DocumentProcessor",
    "NoOpDocumentProcessor",
    "ProcessedDocument",
    "execute_processor",
]
