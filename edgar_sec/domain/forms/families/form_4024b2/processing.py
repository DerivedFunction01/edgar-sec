"""Form 40-24B2 family processing profile."""

from __future__ import annotations

from edgar_sec.domain.forms.common.processing import (
    AcquisitionOperation,
    DocumentProcessingProfile,
)

PROFILE_FORM_4024B2 = DocumentProcessingProfile(
    family="40-24B2",
    version="v1",
    allowed_operations=frozenset(
        {
            AcquisitionOperation.RAW,
            AcquisitionOperation.RENDER_TO_TXT,
        }
    ),
    preferred_operation=AcquisitionOperation.RENDER_TO_TXT,
)

__all__ = ["PROFILE_FORM_4024B2"]
