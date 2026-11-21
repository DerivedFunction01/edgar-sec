"""Form D family processing profile."""

from __future__ import annotations

from edgar_sec.domain.forms.common.processing import (
    AcquisitionOperation,
    DocumentProcessingProfile,
)
from edgar_sec.domain.forms.families.form_d.reports import FormDReport

PROFILE_FORM_D = DocumentProcessingProfile(
    family="D",
    version="v1",
    allowed_operations=frozenset(
        {
            AcquisitionOperation.RAW,
            AcquisitionOperation.RENDER_TO_XML,
        }
    ),
    report_class=FormDReport,
    preferred_operation=AcquisitionOperation.RENDER_TO_XML,
    review_analyzer="edgar_sec.engine.forms.form_d.analysis",
)

__all__ = ["PROFILE_FORM_D"]
