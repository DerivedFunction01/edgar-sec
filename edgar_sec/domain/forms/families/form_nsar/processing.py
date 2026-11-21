"""Form NSAR family processing profile."""

from __future__ import annotations

from edgar_sec.domain.forms.common.processing import (
    AcquisitionOperation,
    DocumentProcessingProfile,
)
from edgar_sec.domain.forms.families.form_nsar.reports import FormNSARReport

PROFILE_FORM_NSAR = DocumentProcessingProfile(
    family="NSAR",
    version="v1",
    allowed_operations=frozenset(
        {
            AcquisitionOperation.RAW,
            AcquisitionOperation.RENDER_TO_TXT,
        }
    ),
    report_class=FormNSARReport,
    preferred_operation=AcquisitionOperation.RENDER_TO_TXT,
    review_analyzer="edgar_sec.engine.forms.form_nsar.analysis",
    has_sections=True,
)

__all__ = ["PROFILE_FORM_NSAR"]
