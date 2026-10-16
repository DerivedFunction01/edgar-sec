"""Current report family processing profile.

Defines the DocumentProcessingProfile for Form 8-K current reports.
"""

from edgar_sec.domain.forms.common.processing import (
    AcquisitionOperation,
    DocumentProcessingProfile,
)
from edgar_sec.domain.forms.families.current.reports import CurrentReport

# Processing profile for current family (8-K)
PROFILE = DocumentProcessingProfile(
    family="8-K",
    version="v1",
    allowed_operations=frozenset(
        {
            AcquisitionOperation.RAW,
            AcquisitionOperation.RENDER_TO_TXT,
        }
    ),
    report_class=CurrentReport,
    preferred_operation=AcquisitionOperation.RENDER_TO_TXT,
    has_toc=False,
    has_sections=True,
    has_notes=False,
)

__all__ = ["PROFILE"]
