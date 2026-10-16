"""Registration statement family profiles for Form S-1."""

from __future__ import annotations

from edgar_sec.domain.forms.common.aliases import aliases_for_family
from edgar_sec.domain.forms.common.exhibits import PrimaryReportProfile
from edgar_sec.domain.forms.families.registration.evidence import (
    REGISTRATION_REPORT_TITLES,
)

PRIMARY_PROFILE_S1 = PrimaryReportProfile(
    family="S-1",
    version="v1",
    statutory_titles=REGISTRATION_REPORT_TITLES,
    designator_tokens=aliases_for_family("S-1"),
    commission_header_required=True,
)

__all__ = [
    "PRIMARY_PROFILE_S1",
]
