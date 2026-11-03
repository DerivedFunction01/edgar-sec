"""Form 40-F family processing profile."""

from __future__ import annotations

from edgar_sec.domain.forms.common.processing import (
    AcquisitionOperation,
    DocumentProcessingProfile,
)
from edgar_sec.domain.forms.families.form_40f.reports import Form40FReport

PROFILE_FORM_40F = DocumentProcessingProfile(
    family="40-F",
    version="v1",
    allowed_operations=frozenset(
        {
            AcquisitionOperation.RAW,
            AcquisitionOperation.RENDER_TO_TXT,
        }
    ),
    report_class=Form40FReport,
    preferred_operation=AcquisitionOperation.RENDER_TO_TXT,
    review_analyzer="edgar_sec.engine.forms.form_40f.analysis",
    has_toc=True,
    has_sections=True,
    has_notes=True,
    has_xbrl=True,
)

__all__ = ["PROFILE_FORM_40F"]
