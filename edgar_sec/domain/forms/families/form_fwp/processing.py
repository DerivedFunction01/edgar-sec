"""Free writing prospectus family processing profile."""

from edgar_sec.domain.forms.common.processing import (
    AcquisitionOperation,
    DocumentProcessingProfile,
)
from edgar_sec.domain.forms.families.form_fwp.reports import FormFWPReport

PROFILE_FORM_FWP = DocumentProcessingProfile(
    family="FWP",
    version="v1",
    allowed_operations=frozenset(
        {
            AcquisitionOperation.RAW,
            AcquisitionOperation.RENDER_TO_TXT,
        }
    ),
    report_class=FormFWPReport,
    preferred_operation=AcquisitionOperation.RENDER_TO_TXT,
    review_analyzer="edgar_sec.engine.forms.form_fwp.analysis",
    has_sections=True,
)

__all__ = ["PROFILE_FORM_FWP"]
