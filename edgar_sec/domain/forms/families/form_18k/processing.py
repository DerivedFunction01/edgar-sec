"""Form 18-K family processing profile."""

from __future__ import annotations

from edgar_sec.domain.forms.common.processing import (
    AcquisitionOperation,
    DocumentProcessingProfile,
)
from edgar_sec.domain.forms.families.form_18k.reports import Form18KReport

PROFILE_FORM_18K = DocumentProcessingProfile(
    family="18-K",
    version="v1",
    allowed_operations=frozenset(
        {
            AcquisitionOperation.RAW,
            AcquisitionOperation.RENDER_TO_TXT,
        }
    ),
    report_class=Form18KReport,
    preferred_operation=AcquisitionOperation.RENDER_TO_TXT,
    has_sections=True,
)

__all__ = ["PROFILE_FORM_18K"]
