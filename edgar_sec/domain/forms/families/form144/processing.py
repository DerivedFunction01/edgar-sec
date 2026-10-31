"""Form 144 family processing profiles."""

from __future__ import annotations

from edgar_sec.domain.forms.common.processing import (
    AcquisitionOperation,
    DocumentProcessingProfile,
)
from edgar_sec.domain.forms.families.form144.reports import Form144Report

PROFILE_FORM_144 = DocumentProcessingProfile(
    family="144",
    version="v1",
    allowed_operations=frozenset(
        {
            AcquisitionOperation.RAW,
            AcquisitionOperation.RENDER_TO_XML,
        }
    ),
    report_class=Form144Report,
    preferred_operation=AcquisitionOperation.RENDER_TO_XML,
    review_analyzer="edgar_sec.engine.forms.form144.analysis",
)

__all__ = ["PROFILE_FORM_144"]
