"""Form N-CSR family processing profile."""

from __future__ import annotations

from edgar_sec.domain.forms.common.processing import (
    AcquisitionOperation,
    DocumentProcessingProfile,
)
from edgar_sec.domain.forms.families.form_ncsr.reports import FormNCsrReport

PROFILE_FORM_NCSR = DocumentProcessingProfile(
    family="N-CSR",
    version="v1",
    allowed_operations=frozenset(
        {
            AcquisitionOperation.RAW,
            AcquisitionOperation.RENDER_TO_TXT,
        }
    ),
    report_class=FormNCsrReport,
    preferred_operation=AcquisitionOperation.RENDER_TO_TXT,
    review_analyzer="edgar_sec.engine.forms.form_ncsr.analysis",
    has_sections=True,
)

__all__ = ["PROFILE_FORM_NCSR"]
