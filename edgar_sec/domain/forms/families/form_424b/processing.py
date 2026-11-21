"""Prospectus family processing profile."""

from edgar_sec.domain.forms.common.processing import (
    AcquisitionOperation,
    DocumentProcessingProfile,
)
from edgar_sec.domain.forms.families.form_424b.reports import Form424BReport

PROFILE_FORM_424B = DocumentProcessingProfile(
    family="424B",
    version="v1",
    allowed_operations=frozenset(
        {
            AcquisitionOperation.RAW,
            AcquisitionOperation.RENDER_TO_TXT,
        }
    ),
    report_class=Form424BReport,
    preferred_operation=AcquisitionOperation.RENDER_TO_TXT,
    review_analyzer="edgar_sec.engine.forms.form_424b.analysis",
    has_toc=True,
    has_sections=True,
    has_notes=True,
    has_xbrl=True,
)

__all__ = ["PROFILE_FORM_424B"]
