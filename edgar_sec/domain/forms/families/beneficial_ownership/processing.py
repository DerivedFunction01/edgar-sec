from __future__ import annotations

from edgar_sec.domain.forms.common.processing import (
    AcquisitionOperation,
    DocumentProcessingProfile,
)

PROFILE_SCHEDULE_13D = DocumentProcessingProfile(
    family="13D",
    version="v1",
    allowed_operations=frozenset(
        {
            AcquisitionOperation.RAW,
            AcquisitionOperation.RENDER_TO_TXT,
            AcquisitionOperation.RENDER_TO_XML,
        }
    ),
    preferred_operation=AcquisitionOperation.RENDER_TO_XML,
    review_analyzer="edgar_sec.engine.forms.beneficial_ownership.analysis",
    has_sections=True,
)

PROFILE_SCHEDULE_13G = DocumentProcessingProfile(
    family="13G",
    version="v1",
    allowed_operations=frozenset(
        {
            AcquisitionOperation.RAW,
            AcquisitionOperation.RENDER_TO_TXT,
            AcquisitionOperation.RENDER_TO_XML,
        }
    ),
    preferred_operation=AcquisitionOperation.RENDER_TO_XML,
    review_analyzer="edgar_sec.engine.forms.beneficial_ownership.analysis",
    has_sections=True,
)

__all__ = ["PROFILE_SCHEDULE_13D", "PROFILE_SCHEDULE_13G"]
