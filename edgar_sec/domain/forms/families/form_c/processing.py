"""Form C family processing profile."""

from __future__ import annotations

from edgar_sec.domain.forms.common.processing import (
    AcquisitionOperation,
    DocumentProcessingProfile,
)
from edgar_sec.domain.forms.families.form_c.reports import FormCReport

PROFILE_FORM_C = DocumentProcessingProfile(
    family="C",
    version="v1",
    allowed_operations=frozenset(
        {
            AcquisitionOperation.RAW,
            AcquisitionOperation.RENDER_TO_XML,
        }
    ),
    report_class=FormCReport,
    preferred_operation=AcquisitionOperation.RENDER_TO_XML,
    review_analyzer="edgar_sec.engine.forms.form_c.analysis",
)

__all__ = ["PROFILE_FORM_C"]
