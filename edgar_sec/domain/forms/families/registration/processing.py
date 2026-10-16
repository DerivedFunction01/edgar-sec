"""Registration statement family processing profile."""

from edgar_sec.domain.forms.common.processing import (
    AcquisitionOperation,
    DocumentProcessingProfile,
)
from edgar_sec.domain.forms.families.registration.reports import RegistrationReport

PROFILE_S1 = DocumentProcessingProfile(
    family="S-1",
    version="v1",
    allowed_operations=frozenset(
        {
            AcquisitionOperation.RAW,
            AcquisitionOperation.RENDER_TO_TXT,
        }
    ),
    report_class=RegistrationReport,
    preferred_operation=AcquisitionOperation.RENDER_TO_TXT,
    review_analyzer="edgar_sec.engine.forms.registration.analysis",
    has_toc=True,
    has_sections=True,
    has_notes=True,
    has_xbrl=True,
)

__all__ = ["PROFILE_S1"]
