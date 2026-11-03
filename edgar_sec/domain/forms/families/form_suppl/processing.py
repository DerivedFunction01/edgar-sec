"""SUPPL family processing profile."""

from __future__ import annotations

from edgar_sec.domain.forms.common.processing import (
    AcquisitionOperation,
    DocumentProcessingProfile,
)
from edgar_sec.domain.forms.families.form_suppl.reports import FormSupplReport

PROFILE_FORM_SUPPL = DocumentProcessingProfile(
    family="SUPPL",
    version="v1",
    allowed_operations=frozenset(
        {
            AcquisitionOperation.RAW,
            AcquisitionOperation.RENDER_TO_TXT,
        }
    ),
    report_class=FormSupplReport,
    preferred_operation=AcquisitionOperation.RENDER_TO_TXT,
    review_analyzer="edgar_sec.engine.forms.form_suppl.analysis",
    has_toc=True,
    has_sections=True,
    has_notes=False,
    has_xbrl=False,
)

__all__ = ["PROFILE_FORM_SUPPL"]
