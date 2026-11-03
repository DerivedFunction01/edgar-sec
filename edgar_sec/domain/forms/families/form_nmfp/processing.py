"""Form N-MFP family processing profile."""

from __future__ import annotations

from edgar_sec.domain.forms.common.processing import (
    AcquisitionOperation,
    DocumentProcessingProfile,
)
from edgar_sec.domain.forms.families.form_nmfp.reports import FormNMfpReport

PROFILE_N_MFP = DocumentProcessingProfile(
    family="N-MFP",
    version="v1",
    allowed_operations=frozenset(
        {
            AcquisitionOperation.RAW,
            AcquisitionOperation.RENDER_TO_XML,
        }
    ),
    report_class=FormNMfpReport,
    preferred_operation=AcquisitionOperation.RENDER_TO_XML,
    review_analyzer="edgar_sec.engine.forms.form_nmfp.analysis",
)

__all__ = ["PROFILE_N_MFP"]
