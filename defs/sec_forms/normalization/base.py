"""Form normalization pipeline protocol and interface contracts."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from defs.sec_documents.models import PreprocessedDocument
from defs.sec_forms.normalization.models import NormalizationResult
from defs.sec_forms.page_markers import PageArtifactPolicy


@runtime_checkable
class FormNormalizationPipeline(Protocol):
    """Protocol for form-family specific normalization pipelines."""

    def normalize(
        self,
        preprocessed: PreprocessedDocument,
        metadata: dict[str, Any] | None = None,
        *,
        page_artifact_policy: PageArtifactPolicy = PageArtifactPolicy.STRIP,
        tag_untagged_tables: bool = False,
    ) -> NormalizationResult:
        """Execute form-aware normalization on a preprocessed document."""
        ...


__all__ = ["FormNormalizationPipeline"]
