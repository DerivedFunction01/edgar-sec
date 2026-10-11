"""Quarterly report family processing profile.

Defines the DocumentProcessingProfile for Form 10-Q quarterly reports.
"""

from edgar_sec.domain.forms.common.processing import (
    AcquisitionOperation,
    DocumentProcessingProfile,
)

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
)

__all__ = ["PROFILE"]
