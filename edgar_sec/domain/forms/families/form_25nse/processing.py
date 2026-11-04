"""Form 25-NSE family processing profile."""

from __future__ import annotations

from edgar_sec.domain.forms.common.processing import (
    AcquisitionOperation,
    DocumentProcessingProfile,
)
from edgar_sec.domain.forms.families.form_25nse.reports import Form25NseReport

PROFILE_FORM_25NSE = DocumentProcessingProfile(
    family="25-NSE",
    version="v1",
    allowed_operations=frozenset(
        {
            AcquisitionOperation.RAW,
            AcquisitionOperation.RENDER_TO_XML,
        }
    ),
    report_class=Form25NseReport,
    preferred_operation=AcquisitionOperation.RENDER_TO_XML,
    review_analyzer="edgar_sec.engine.forms.form_25nse.analysis",
)

__all__ = ["PROFILE_FORM_25NSE"]
