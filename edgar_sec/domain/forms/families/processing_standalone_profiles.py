"""Standalone processing profiles for families with no family package."""

from __future__ import annotations

from edgar_sec.domain.forms.common.processing import (
    AcquisitionOperation,
    DocumentProcessingProfile,
)


# ARS rides the generic segmentation profile (T4.10 disposition):
# no family package, no taxonomy, no analyzer of its own.
PROFILE_ARS = DocumentProcessingProfile(
    family="ARS",
    version="v1",
    allowed_operations=frozenset(
        {AcquisitionOperation.RAW, AcquisitionOperation.RENDER_TO_TXT}
    ),
    preferred_operation=AcquisitionOperation.RENDER_TO_TXT,
)


# Raw-ride profiles (standing disposition): the primary is a native
# XML submission, so no text path exists and no family package is built.
PROFILE_NCR = DocumentProcessingProfile(
    family="N-CR",
    version="v1",
    allowed_operations=frozenset({AcquisitionOperation.RAW}),
    preferred_operation=AcquisitionOperation.RAW,
)

PROFILE_ATSN = DocumentProcessingProfile(
    family="ATS-N",
    version="v1",
    allowed_operations=frozenset({AcquisitionOperation.RAW}),
    preferred_operation=AcquisitionOperation.RAW,
)

PROFILE_MAI = DocumentProcessingProfile(
    family="MA-I",
    version="v1",
    allowed_operations=frozenset({AcquisitionOperation.RAW}),
    preferred_operation=AcquisitionOperation.RAW,
)
