"""Form 40-17G family processing profile."""

from __future__ import annotations

from edgar_sec.domain.forms.common.processing import (
    AcquisitionOperation,
    DocumentProcessingProfile,
)
from edgar_sec.domain.forms.families.form_4017g.reports import Form4017GReport

PROFILE_FORM_4017G = DocumentProcessingProfile(
    family="40-17G",
    version="v1",
    allowed_operations=frozenset(
        {
            AcquisitionOperation.RAW,
            AcquisitionOperation.RENDER_TO_TXT,
        }
    ),
    report_class=Form4017GReport,
    preferred_operation=AcquisitionOperation.RENDER_TO_TXT,
    has_sections=True,
)

__all__ = ["PROFILE_FORM_4017G"]
