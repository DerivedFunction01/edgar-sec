"""Annual report family processing profile.

Defines the DocumentProcessingProfile for Form 10-K and Form 20-F annual reports.
"""

from edgar_sec.domain.forms.common.processing import (
    AcquisitionOperation,
    DocumentProcessingProfile,
)

# Processing profile for annual family (10-K, 20-F)
PROFILE = DocumentProcessingProfile(
    family="10-K",
    version="v1",
    allowed_operations=frozenset(
        {
            AcquisitionOperation.RAW,
            AcquisitionOperation.RENDER_TO_TXT,
        }
    ),
)

PROFILE_20F = DocumentProcessingProfile(
    family="20-F",
    version="v1",
    allowed_operations=frozenset(
        {
            AcquisitionOperation.RAW,
            AcquisitionOperation.RENDER_TO_TXT,
        }
    ),
)

__all__ = ["PROFILE", "PROFILE_20F"]
