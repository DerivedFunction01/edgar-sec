"""Form F-3 family processing profile."""

from __future__ import annotations

from edgar_sec.domain.forms.common.processing import (
    AcquisitionOperation,
    DocumentProcessingProfile,
)
from edgar_sec.domain.forms.families.form_f3.reports import FormF3Report

PROFILE_FORM_F3 = DocumentProcessingProfile(
    family="F-3",
    version="v1",
    allowed_operations=frozenset(
        {
            AcquisitionOperation.RAW,
            AcquisitionOperation.RENDER_TO_TXT,
        }
    ),
    report_class=FormF3Report,
    preferred_operation=AcquisitionOperation.RENDER_TO_TXT,
    review_analyzer="edgar_sec.engine.forms.form_f3.analysis",
    has_toc=True,
    has_sections=True,
    has_notes=True,
    has_xbrl=True,
)

__all__ = ["PROFILE_FORM_F3"]
