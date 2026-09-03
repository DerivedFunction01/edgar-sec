"""Document processors package for Phase 025 webpage & document storage."""

from __future__ import annotations

from ..core.schemas import DocumentLocator, doc_id
from .base import (
    DocumentProcessor,
    NoOpDocumentProcessor,
    ProcessedDocument,
    execute_processor,
)
from .forms import (
    DecisionAction,
    Form8KEvaluator,
    Form8KNormalizer,
    Form10KEvaluator,
    Form10KNormalizer,
    Form10QEvaluator,
    Form10QNormalizer,
    FormEvaluator,
    FormNormalizer,
    GenericFormEvaluator,
    GenericFormNormalizer,
    PreprocessedDocument,
    RefetchDecision,
)
from .normalizer import DeepNormalizer, NormalizationResult
from .preprocessor import GenericPreprocessor
from .router import FormRouter


class DefaultFilingProcessor(DocumentProcessor):
    """Default end-to-end filing processor executing the multi-stage lifecycle."""

    processor_fingerprint = "default-filing-processor:v1"
    representation = "normalized-text"

    def __init__(
        self,
        preprocessor: GenericPreprocessor | None = None,
        router: FormRouter | None = None,
        normalizer: DeepNormalizer | None = None,
    ) -> None:
        self.preprocessor = preprocessor or GenericPreprocessor()
        self.router = router or FormRouter()
        self.normalizer = normalizer or DeepNormalizer(router=self.router)

    async def process(
        self,
        raw_bytes: bytes,
        locator: DocumentLocator,
    ) -> ProcessedDocument:
        """Process raw filing bytes through the normalization pipeline."""
        # Stage 1: Generic Preprocessing
        preprocessed = self.preprocessor.preprocess(
            raw_bytes, metadata={"form": locator.form}
        )

        # Stage 2: Form Routing & Refetch Evaluation
        decision = self.router.evaluate(preprocessed, locator)

        # Stage 3: Deep Normalization & Table Alignment
        normalization = self.normalizer.normalize_result(
            preprocessed, metadata={"form": locator.form}
        )
        normalized_text = normalization.text

        output_payload = normalized_text.encode("utf-8")

        cover_boundary = normalization.cover_boundary
        body = normalization.body_start
        toc = normalization.toc_span
        closing = normalization.closing_span
        reflow = normalization.reflow
        reflow_counts: dict[str, int] = {}
        if reflow is not None:
            for span_decision in reflow.decisions:
                reflow_counts[span_decision.action] = (
                    reflow_counts.get(span_decision.action, 0) + 1
                )
        page_analysis = normalization.page_analysis or preprocessed.page_analysis
        page_decisions = page_analysis.decisions if page_analysis is not None else ()
        meta = {
            "is_stub": decision.is_stub,
            "category": decision.category,
            "decision_action": decision.action.value,
            "decision_reason": decision.reason,
            "target_exhibit": decision.target_exhibit,
            "detected_encoding": preprocessed.detected_encoding,
            "word_count": len(normalized_text.split()),
            "cover_boundary_method": cover_boundary.method.value,
            "cover_boundary_line": cover_boundary.end_line,
            "cover_boundary_confidence": cover_boundary.confidence,
            "cover_boundary_start_line": cover_boundary.start_line,
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
            "page_marker_count": len(page_analysis.markers) if page_analysis else 0,
            "page_marker_removed_count": sum(
                decision.action.value == "remove" for decision in page_decisions
            ),
            "page_marker_normalized_count": sum(
                decision.action.value == "normalize" for decision in page_decisions
            ),
            "page_marker_preserved_count": sum(
                decision.action.value == "preserve" for decision in page_decisions
            ),
            "page_marker_run_count": len(page_analysis.page_number_runs)
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
                    for run in page_analysis.page_number_runs[:64]
                ]
                if page_analysis
                else []
            ),
            "page_marker_inferred_boundary_count": len(
                page_analysis.inferred_boundaries
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
            "page_marker_unresolved_count": len(page_analysis.unresolved)
            if page_analysis
            else 0,
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


__all__ = [
    "DecisionAction",
    "DeepNormalizer",
    "DefaultFilingProcessor",
    "DocumentProcessor",
    "Form8KEvaluator",
    "Form8KNormalizer",
    "Form10KEvaluator",
    "Form10KNormalizer",
    "Form10QEvaluator",
    "Form10QNormalizer",
    "FormEvaluator",
    "FormNormalizer",
    "FormRouter",
    "GenericFormEvaluator",
    "GenericFormNormalizer",
    "GenericPreprocessor",
    "NoOpDocumentProcessor",
    "NormalizationResult",
    "PreprocessedDocument",
    "ProcessedDocument",
    "RefetchDecision",
    "execute_processor",
]
