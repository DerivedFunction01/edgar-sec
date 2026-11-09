"""Form 40-17F1 family processing profile."""

from __future__ import annotations

from edgar_sec.domain.forms.common.processing import (
    AcquisitionOperation,
    DocumentProcessingProfile,
)
from edgar_sec.domain.forms.families.form_4017f1.reports import Form4017F1Report

PROFILE_FORM_4017F1 = DocumentProcessingProfile(
    family="40-17F1",
    version="v1",
    allowed_operations=frozenset(
        {
            AcquisitionOperation.RAW,
            AcquisitionOperation.RENDER_TO_TXT,
        }
    ),
    report_class=Form4017F1Report,
    preferred_operation=AcquisitionOperation.RENDER_TO_TXT,
    has_sections=True,
)

__all__ = ["PROFILE_FORM_4017F1"]
