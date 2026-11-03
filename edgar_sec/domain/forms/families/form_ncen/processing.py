"""Form N-CEN family processing profile."""

from __future__ import annotations

from edgar_sec.domain.forms.common.processing import (
    AcquisitionOperation,
    DocumentProcessingProfile,
)
from edgar_sec.domain.forms.families.form_ncen.reports import FormNCenReport

PROFILE_N_CEN = DocumentProcessingProfile(
    family="N-CEN",
    version="v1",
    allowed_operations=frozenset(
        {
            AcquisitionOperation.RAW,
            AcquisitionOperation.RENDER_TO_XML,
        }
    ),
    report_class=FormNCenReport,
    preferred_operation=AcquisitionOperation.RENDER_TO_XML,
    review_analyzer="edgar_sec.engine.forms.form_ncen.analysis",
)

__all__ = ["PROFILE_N_CEN"]
