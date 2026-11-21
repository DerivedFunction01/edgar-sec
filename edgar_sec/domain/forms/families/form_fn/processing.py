"""Form F-N family processing profile."""

from __future__ import annotations

from edgar_sec.domain.forms.common.processing import (
    AcquisitionOperation,
    DocumentProcessingProfile,
)
from edgar_sec.domain.forms.families.form_fn.reports import FormFnReport

PROFILE_FORM_FN = DocumentProcessingProfile(
    family="F-N",
    version="v1",
    allowed_operations=frozenset(
        {
            AcquisitionOperation.RAW,
            AcquisitionOperation.RENDER_TO_TXT,
        }
    ),
    report_class=FormFnReport,
    preferred_operation=AcquisitionOperation.RENDER_TO_TXT,
    review_analyzer="edgar_sec.engine.forms.form_fn.analysis",
    has_toc=False,
    has_sections=False,
    has_notes=False,
    has_xbrl=False,
)

__all__ = ["PROFILE_FORM_FN"]
