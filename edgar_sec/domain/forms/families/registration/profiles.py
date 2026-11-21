"""Registration statement family profiles for Form S-1."""

from __future__ import annotations

from edgar_sec.domain.forms.common.aliases import aliases_for_family
from edgar_sec.domain.forms.common.exhibits import PrimaryReportProfile
from edgar_sec.domain.forms.families.registration.evidence import (
    REGISTRATION_REPORT_TITLES,
    S3_REPORT_TITLES,
    S4_REPORT_TITLES,
    S8_REPORT_TITLES,
)

PRIMARY_PROFILE_S1 = PrimaryReportProfile(
    family="S-1",
    version="v1",
    statutory_titles=REGISTRATION_REPORT_TITLES,
    designator_tokens=aliases_for_family("S-1"),
    commission_header_required=True,
)

PRIMARY_PROFILE_S3 = PrimaryReportProfile(
    family="S-3",
    version="v1",
    statutory_titles=S3_REPORT_TITLES,
    designator_tokens=aliases_for_family("S-3"),
    commission_header_required=True,
)

PRIMARY_PROFILE_S4 = PrimaryReportProfile(
    family="S-4",
    version="v1",
    statutory_titles=S4_REPORT_TITLES,
    designator_tokens=aliases_for_family("S-4"),
    commission_header_required=True,
)

PRIMARY_PROFILE_S8 = PrimaryReportProfile(
    family="S-8",
    version="v1",
    statutory_titles=S8_REPORT_TITLES,
    designator_tokens=aliases_for_family("S-8"),
    commission_header_required=True,
)

__all__ = [
    "PRIMARY_PROFILE_S1",
    "PRIMARY_PROFILE_S3",
    "PRIMARY_PROFILE_S4",
    "PRIMARY_PROFILE_S8",
]
