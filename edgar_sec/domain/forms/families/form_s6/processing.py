"""Form S-6 family processing profile."""

from __future__ import annotations

from edgar_sec.domain.forms.common.processing import (
    AcquisitionOperation,
    DocumentProcessingProfile,
)
from edgar_sec.domain.forms.families.form_s6.reports import FormS6Report

PROFILE_FORM_S6 = DocumentProcessingProfile(
    family="S-6",
    version="v1",
    allowed_operations=frozenset(
        {
            AcquisitionOperation.RAW,
            AcquisitionOperation.RENDER_TO_TXT,
        }
    ),
    report_class=FormS6Report,
    preferred_operation=AcquisitionOperation.RENDER_TO_TXT,
    has_sections=True,
    has_toc=True,
)

__all__ = ["PROFILE_FORM_S6"]
