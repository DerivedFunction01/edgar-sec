"""Form 15 family processing profile."""

from edgar_sec.domain.forms.common.processing import (
    AcquisitionOperation,
    DocumentProcessingProfile,
)
from edgar_sec.domain.forms.families.form_15.reports import Form15Report

PROFILE_FORM_15 = DocumentProcessingProfile(
    family="15",
    version="v1",
    allowed_operations=frozenset(
        {
            AcquisitionOperation.RAW,
            AcquisitionOperation.RENDER_TO_TXT,
        }
    ),
    report_class=Form15Report,
    preferred_operation=AcquisitionOperation.RENDER_TO_TXT,
    review_analyzer="edgar_sec.engine.forms.form_15.analysis",
    has_toc=False,
    has_sections=False,
    has_notes=False,
    has_xbrl=False,
)

__all__ = ["PROFILE_FORM_15"]
