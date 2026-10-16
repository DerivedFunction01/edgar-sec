"""Quarterly report family processing profile.

Defines the DocumentProcessingProfile for Form 10-Q quarterly reports.
"""

from edgar_sec.domain.forms.common.processing import (
    AcquisitionOperation,
    DocumentProcessingProfile,
)
from edgar_sec.domain.forms.families.quarterly.reports import QuarterlyReport

# Processing profile for quarterly family (10-Q)
PROFILE = DocumentProcessingProfile(
    family="10-Q",
    version="v1",
    allowed_operations=frozenset(
        {
            AcquisitionOperation.RAW,
            AcquisitionOperation.RENDER_TO_TXT,
        }
    ),
    report_class=QuarterlyReport,
    preferred_operation=AcquisitionOperation.RENDER_TO_TXT,
    review_analyzer="edgar_sec.engine.forms.analysis",
    has_toc=True,
    has_sections=True,
    has_notes=True,
    has_xbrl=True,
)

__all__ = ["PROFILE"]
