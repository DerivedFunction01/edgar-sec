"""Normalization engine orchestrating form pipeline resolution and execution."""

from __future__ import annotations

from typing import Any

from defs.sec_documents.models import PreprocessedDocument
from defs.sec_forms.normalization.models import NormalizationResult
from defs.sec_forms.normalization.registry import get_pipeline
from defs.sec_forms.page_markers import PageArtifactPolicy


class DocumentNormalizer:
    """Multi-stage document normalizer dispatching to form-specific pipelines."""

    def __init__(self, *, tag_untagged_tables: bool = False) -> None:
        self.tag_untagged_tables = tag_untagged_tables

    def normalize(
        self,
        preprocessed: PreprocessedDocument,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Normalize document and return clean normalized text."""
        return self.normalize_result(preprocessed, metadata).text

    def normalize_result(
        self,
        preprocessed: PreprocessedDocument,
        metadata: dict[str, Any] | None = None,
        *,
        page_artifact_policy: PageArtifactPolicy = PageArtifactPolicy.STRIP,
    ) -> NormalizationResult:
        """Normalize document and return complete structural NormalizationResult."""
        form = (metadata or {}).get("form") or preprocessed.metadata.get("form")
        pipeline = get_pipeline(form)
        return pipeline.normalize(
            preprocessed,
            metadata,
            page_artifact_policy=page_artifact_policy,
            tag_untagged_tables=self.tag_untagged_tables,
        )


def normalize_document(
    preprocessed: PreprocessedDocument,
    metadata: dict[str, Any] | None = None,
    *,
    page_artifact_policy: PageArtifactPolicy = PageArtifactPolicy.STRIP,
    tag_untagged_tables: bool = False,
) -> NormalizationResult:
    """Convenience helper to normalize a preprocessed document using its form profile."""
    normalizer = DocumentNormalizer(tag_untagged_tables=tag_untagged_tables)
    return normalizer.normalize_result(
        preprocessed, metadata, page_artifact_policy=page_artifact_policy
    )


__all__ = [
    "DocumentNormalizer",
    "normalize_document",
]
