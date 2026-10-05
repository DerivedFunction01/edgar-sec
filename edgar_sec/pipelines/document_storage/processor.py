"""Document processing: raw payload in, normalized text and triage out.

Triage rides in the metadata rather than splitting the work: deciding a document is
a stub requires having normalized it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from edgar_sec.domain.document.acquisition import AcquiredSubmission
from edgar_sec.domain.document.models import DocumentLocator
from edgar_sec.domain.document.route import (
    REPRESENTATION_RAW,
    DocumentRoute,
    mime_type_for_suffix,
)
from edgar_sec.domain.forms.common.decisions import EvaluatorDecision
from edgar_sec.engine.document.page_markers.models import PageMarkerAction
from edgar_sec.engine.forms.normalize import NormalizationResult, normalize_document
from edgar_sec.engine.forms.plugins.registry import get_plugin
from edgar_sec.foundation.hashing import sha256_text

#: Bumped when normalization output changes shape; the fingerprint gates chunk reuse,
#: so an older processor's checkpoints are not interchangeable with this one's.
PROCESSOR_SCHEMA_VERSION = 2

#: Identifies *which* normalization produced a text.
PROCESSOR_FINGERPRINT = f"document-storage-normalizer:v{PROCESSOR_SCHEMA_VERSION}"

#: Distinct so one processor's checkpoint is never reused by the other.
PASS_THROUGH_FINGERPRINT = "raw-pass-through"


def count_words(text: str) -> int:
    """Count whitespace-delimited words."""
    return len(text.split()) if text else 0


def _reflow_counts(result: NormalizationResult) -> dict[str, int]:
    counts: dict[str, int] = {}
    if result.reflow is None:
        return counts
    for decision in result.reflow.decisions:
        counts[decision.action] = counts.get(decision.action, 0) + 1
    return counts


def _page_counts(result: NormalizationResult) -> tuple[int, int, int]:
    """Return ``(marker_count, stripped_count, preserved_count)``."""
    analysis = result.page_analysis
    if analysis is None:
        return 0, 0, 0
    stripped = sum(
        1
        for decision in analysis.decisions
        if decision.action == PageMarkerAction.REMOVE
    )
    return len(analysis.markers), stripped, len(analysis.decisions) - stripped


def _boundary_metadata(result: NormalizationResult) -> dict[str, Any]:
    boundary = result.cover_boundary
    body = result.body_start
    closing = result.closing_span
    return {
        "cover_boundary_method": boundary.method.value,
        # The detected line is pre-reflow and therefore stable; the reported
        # end_line is in final-text coordinates and may have shifted.
        "cover_boundary_detected_line": result.cover_boundary_detected_line,
        "cover_start_detected_line": result.cover_start_detected_line,
        "cover_boundary_line": boundary.end_line,
        "cover_boundary_confidence": boundary.confidence,
        "cover_boundary_start_line": boundary.start_line,
        "cover_boundary_approximate": boundary.approximate,
        "body_start_line": None if body is None else body.line,
        "body_heading_line": None if body is None else body.heading_line,
        "body_first_unit_line": None if body is None else body.first_unit_line,
        "body_anchor_type": None if body is None else body.anchor_type,
        "body_confidence": None if body is None else body.confidence,
        "body_delayed": None if body is None else body.delayed,
        "body_rejection_reasons": [] if body is None else list(body.rejection_reasons),
        "closing_start_line": None if closing is None else closing.start_line,
        "closing_kind": None if closing is None else closing.kind,
        "closing_confidence": None if closing is None else closing.confidence,
    }


@dataclass(frozen=True, slots=True)
class ProcessedDocument:
    """One document after processing, with everything a snapshot row needs."""

    document_locator_key: str
    payload: bytes
    byte_size: int
    mime_type: str
    representation: str = REPRESENTATION_RAW
    processor_fingerprint: str = PROCESSOR_FINGERPRINT
    metadata: dict[str, Any] = field(default_factory=dict)
    decision: EvaluatorDecision | None = None

    @property
    def text(self) -> str:
        """The normalized text, or empty for a payload stored verbatim as ``raw``.

        Decoding a raw payload would invent text and misreport the document's size.
        """
        if self.representation == REPRESENTATION_RAW:
            return ""
        return self.payload.decode("utf-8", errors="replace")

    @property
    def word_count(self) -> int:
        return count_words(self.text)

    @property
    def normalized_payload_sha256(self) -> str:
        return sha256_text(self.text)


@runtime_checkable
class DocumentProcessor(Protocol):
    """Transform one acquired submission into a storable form."""

    def process(self, acquired: AcquiredSubmission) -> ProcessedDocument:
        """Process the document one acquisition selected."""


class FilingProcessor:
    """Normalize a filing document and triage it for delegation."""

    __slots__ = ("_fingerprint",)

    def __init__(self, *, fingerprint: str = PROCESSOR_FINGERPRINT) -> None:
        self._fingerprint = fingerprint

    @property
    def processor_fingerprint(self) -> str:
        """Identity a checkpoint must match before it may be reused."""
        return self._fingerprint

    def _store_binary(
        self, raw_bytes: bytes, locator: DocumentLocator
    ) -> ProcessedDocument:
        """Store a binary document verbatim; no text extraction is implemented.

        The filed bytes are the document, so a transformation would replace them with
        something the filer never submitted under a ``raw`` label that was then false.
        """
        return ProcessedDocument(
            document_locator_key=locator.document_locator_key,
            payload=raw_bytes,
            byte_size=len(raw_bytes),
            mime_type=mime_type_for_suffix(locator.document_path),
            representation=REPRESENTATION_RAW,
            processor_fingerprint=self._fingerprint,
            metadata={"normalization": "deferred", "document_route": "binary"},
        )

    def process(self, acquired: AcquiredSubmission) -> ProcessedDocument:
        locator = acquired.requested_locator
        route = acquired.selected_document.content_route
        if route is DocumentRoute.BINARY:
            return self._store_binary(acquired.selected_payload, locator)

        result = normalize_document(
            acquired.selected_payload,
            form=locator.form,
            content_route=route,
        )

        # A paper stub carries no prose, so triage would run an evaluator over a
        # boilerplate pointer and always reach the same verdict.
        plugin = get_plugin(locator.form)
        decision: EvaluatorDecision | None = None
        if plugin.evaluator is not None and route is not DocumentRoute.PAPER:
            decision = plugin.evaluator(result.text)

        marker_count, stripped_count, preserved_count = _page_counts(result)
        metadata: dict[str, Any] = {
            "family": result.family,
            "representation": result.representation,
            "word_count": count_words(result.text),
            "page_marker_count": marker_count,
            "page_marker_stripped_count": stripped_count,
            "page_marker_preserved_count": preserved_count,
            "reflow_unwrap_blocks": _reflow_counts(result).get("unwrap", 0),
            "reflow_preserve_blocks": _reflow_counts(result).get("preserve", 0),
            "reflow_tag_blocks": _reflow_counts(result).get("tag_and_preserve", 0),
            "stage_count": len(result.stage_trace),
            **_boundary_metadata(result),
        }
        if decision is not None:
            metadata.update(
                {
                    "is_stub": decision.is_stub,
                    "category": decision.category,
                    "decision_action": decision.action.value,
                    "decision_reason": decision.reason,
                    "target_exhibit": decision.target_exhibit,
                }
            )

        text = result.text
        payload = text.encode("utf-8")
        return ProcessedDocument(
            document_locator_key=locator.document_locator_key,
            payload=payload,
            byte_size=len(payload),
            mime_type="text/plain",
            representation=result.representation,
            processor_fingerprint=self._fingerprint,
            metadata=metadata,
            decision=decision,
        )


class PassThroughProcessor:
    """Store the payload unprocessed, as bytes."""

    __slots__ = ()

    @property
    def processor_fingerprint(self) -> str:
        """Identity a checkpoint must match before it may be reused."""
        return PASS_THROUGH_FINGERPRINT

    def process(self, acquired: AcquiredSubmission) -> ProcessedDocument:
        return ProcessedDocument(
            document_locator_key=acquired.document_locator_key,
            payload=acquired.selected_payload,
            byte_size=len(acquired.selected_payload),
            mime_type="application/octet-stream",
            representation=REPRESENTATION_RAW,
            processor_fingerprint=PASS_THROUGH_FINGERPRINT,
            metadata={},
        )


__all__ = [
    "PASS_THROUGH_FINGERPRINT",
    "PROCESSOR_FINGERPRINT",
    "PROCESSOR_SCHEMA_VERSION",
    "REPRESENTATION_RAW",
    "DocumentProcessor",
    "FilingProcessor",
    "PassThroughProcessor",
    "ProcessedDocument",
    "count_words",
]
