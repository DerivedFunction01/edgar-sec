"""Form N-PORT family processing profile."""

from __future__ import annotations

from edgar_sec.domain.forms.common.processing import (
    AcquisitionOperation,
    DocumentProcessingProfile,
)
from edgar_sec.domain.forms.families.form_nport.reports import FormNPortReport

PROFILE_NPORT = DocumentProcessingProfile(
    family="N-PORT",
    version="v1",
    allowed_operations=frozenset(
        {
            AcquisitionOperation.RAW,
            AcquisitionOperation.RENDER_TO_XML,
        }
    ),
    report_class=FormNPortReport,
    preferred_operation=AcquisitionOperation.RENDER_TO_XML,
    review_analyzer="edgar_sec.engine.forms.form_nport.analysis",
)

__all__ = ["PROFILE_NPORT"]
