"""Form 13F family processing profile."""

from __future__ import annotations

from edgar_sec.domain.forms.common.processing import (
    AcquisitionOperation,
    DocumentProcessingProfile,
)
from edgar_sec.domain.forms.families.form_13f.reports import Form13FReport

PROFILE_FORM_13F = DocumentProcessingProfile(
    family="13F",
    version="v1",
    allowed_operations=frozenset(
        {
            AcquisitionOperation.RAW,
            AcquisitionOperation.RENDER_TO_XML,
        }
    ),
    report_class=Form13FReport,
    preferred_operation=AcquisitionOperation.RENDER_TO_XML,
    review_analyzer="edgar_sec.engine.forms.form_13f.analysis",
)

__all__ = ["PROFILE_FORM_13F"]
