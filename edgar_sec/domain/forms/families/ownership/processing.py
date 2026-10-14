"""Ownership report family processing profiles."""

from __future__ import annotations

from edgar_sec.domain.forms.common.processing import (
    AcquisitionOperation,
    DocumentProcessingProfile,
)

PROFILE = DocumentProcessingProfile(
    family="4",
    version="v1",
    allowed_operations=frozenset(
        {
            AcquisitionOperation.RAW,
            AcquisitionOperation.RENDER_TO_XML,
        }
    ),
)

__all__ = ["PROFILE"]
