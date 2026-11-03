"""Form N-PX family processing profile."""

from __future__ import annotations

from edgar_sec.domain.forms.common.processing import (
    AcquisitionOperation,
    DocumentProcessingProfile,
)
from edgar_sec.domain.forms.families.form_npx.reports import FormNPxReport

PROFILE_N_PX = DocumentProcessingProfile(
    family="N-PX",
    version="v1",
    allowed_operations=frozenset(
        {
            AcquisitionOperation.RAW,
            AcquisitionOperation.RENDER_TO_XML,
        }
    ),
    report_class=FormNPxReport,
    preferred_operation=AcquisitionOperation.RENDER_TO_XML,
    review_analyzer="edgar_sec.engine.forms.form_npx.analysis",
)

__all__ = ["PROFILE_N_PX"]
