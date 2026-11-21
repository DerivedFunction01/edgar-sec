"""Form N-30D family processing profile."""

from __future__ import annotations

from edgar_sec.domain.forms.common.processing import (
    AcquisitionOperation,
    DocumentProcessingProfile,
)
from edgar_sec.domain.forms.families.form_n30d.reports import FormN30DReport

PROFILE_FORM_N30D = DocumentProcessingProfile(
    family="N-30D",
    version="v1",
    allowed_operations=frozenset(
        {
            AcquisitionOperation.RAW,
            AcquisitionOperation.RENDER_TO_TXT,
        }
    ),
    report_class=FormN30DReport,
    preferred_operation=AcquisitionOperation.RENDER_TO_TXT,
    has_sections=True,
)

__all__ = ["PROFILE_FORM_N30D"]
