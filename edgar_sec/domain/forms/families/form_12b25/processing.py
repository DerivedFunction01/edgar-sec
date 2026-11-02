"""Form 12b-25 family processing profile."""

from edgar_sec.domain.forms.common.processing import (
    AcquisitionOperation,
    DocumentProcessingProfile,
)
from edgar_sec.domain.forms.families.form_12b25.reports import Form12B25Report

PROFILE_FORM_12B25 = DocumentProcessingProfile(
    family="12B-25",
    version="v1",
    allowed_operations=frozenset(
        {
            AcquisitionOperation.RAW,
            AcquisitionOperation.RENDER_TO_TXT,
        }
    ),
    report_class=Form12B25Report,
    preferred_operation=AcquisitionOperation.RENDER_TO_TXT,
    review_analyzer="edgar_sec.engine.forms.form_12b25.analysis",
    has_toc=False,
    has_sections=True,
    has_notes=False,
    has_xbrl=False,
)

__all__ = ["PROFILE_FORM_12B25"]
