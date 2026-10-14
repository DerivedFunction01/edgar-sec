"""Ownership report family processing profiles."""

from __future__ import annotations

from edgar_sec.domain.forms.common.processing import (
    AcquisitionOperation,
    DocumentProcessingProfile,
)

PROFILE_FORM_3 = DocumentProcessingProfile(
    family="3",
    version="v1",
    allowed_operations=frozenset(
        {
            AcquisitionOperation.RAW,
            AcquisitionOperation.RENDER_TO_XML,
        }
    ),
)

PROFILE_FORM_4 = DocumentProcessingProfile(
    family="4",
    version="v1",
    allowed_operations=frozenset(
        {
            AcquisitionOperation.RAW,
            AcquisitionOperation.RENDER_TO_XML,
        }
    ),
)

PROFILE_FORM_5 = DocumentProcessingProfile(
    family="5",
    version="v1",
    allowed_operations=frozenset(
        {
            AcquisitionOperation.RAW,
            AcquisitionOperation.RENDER_TO_XML,
        }
    ),
)

__all__ = ["PROFILE_FORM_3", "PROFILE_FORM_4", "PROFILE_FORM_5"]
