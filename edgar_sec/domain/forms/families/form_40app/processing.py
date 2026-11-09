"""Form 40-APP family processing profile."""

from __future__ import annotations

from edgar_sec.domain.forms.common.processing import (
    AcquisitionOperation,
    DocumentProcessingProfile,
)
from edgar_sec.domain.forms.families.form_40app.reports import Form40AppReport

PROFILE_FORM_40APP = DocumentProcessingProfile(
    family="40-APP",
    version="v1",
    allowed_operations=frozenset(
        {
            AcquisitionOperation.RAW,
            AcquisitionOperation.RENDER_TO_TXT,
        }
    ),
    report_class=Form40AppReport,
    preferred_operation=AcquisitionOperation.RENDER_TO_TXT,
    has_sections=True,
)

__all__ = ["PROFILE_FORM_40APP"]
