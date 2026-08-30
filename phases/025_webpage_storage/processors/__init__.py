"""Document processors package for Phase 025 webpage & document storage."""

from __future__ import annotations

from ..core.schemas import DocumentLocator, detect_mime, doc_id
from .base import (
    DocumentProcessor,
    NoOpDocumentProcessor,
    ProcessedDocument,
    execute_processor,
)
from .forms.base import (
    DecisionAction,
    FormEvaluator,
    PreprocessedDocument,
    RefetchDecision,
)
from .normalizer import DeepNormalizer
from .preprocessor import GenericPreprocessor
from .router import FormRouter


class DefaultFilingProcessor(DocumentProcessor):
    """Default end-to-end filing processor executing the multi-stage lifecycle."""

    def __init__(
        self,
        preprocessor: GenericPreprocessor | None = None,
        router: FormRouter | None = None,
        normalizer: DeepNormalizer | None = None,
    ) -> None:
        self.preprocessor = preprocessor or GenericPreprocessor()
        self.router = router or FormRouter()
        self.normalizer = normalizer or DeepNormalizer()

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
        normalized_text = self.normalizer.normalize(preprocessed)

        output_payload = normalized_text.encode("utf-8")
        out_doc_id = doc_id(locator.accession, locator.document_path)

        meta = {
            "is_stub": decision.is_stub,
            "category": decision.category,
            "decision_action": decision.action.value,
            "decision_reason": decision.reason,
            "target_exhibit": decision.target_exhibit,
            "detected_encoding": preprocessed.detected_encoding,
            "word_count": len(normalized_text.split()),
        }

        return ProcessedDocument(
            doc_id=out_doc_id,
            payload=output_payload,
            byte_size=len(output_payload),
            mime_type=detect_mime(locator.document_path),
            metadata=meta,
        )


__all__ = [
    "DecisionAction",
    "DeepNormalizer",
    "DefaultFilingProcessor",
    "DocumentProcessor",
    "FormEvaluator",
    "FormRouter",
    "GenericPreprocessor",
    "NoOpDocumentProcessor",
    "PreprocessedDocument",
    "ProcessedDocument",
    "RefetchDecision",
    "execute_processor",
]
