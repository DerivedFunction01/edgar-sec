"""Form SD primary-report profile."""

from __future__ import annotations

from edgar_sec.domain.forms.common.aliases import aliases_for_family
from edgar_sec.domain.forms.common.exhibits import PrimaryReportProfile
from edgar_sec.domain.forms.families.form_sd.taxonomy import SD_TITLES

PRIMARY_PROFILE_SD = PrimaryReportProfile(
    family="SD",
    version="v1",
    statutory_titles=SD_TITLES,
    designator_tokens=aliases_for_family("SD"),
    commission_header_required=True,
)

__all__ = ["PRIMARY_PROFILE_SD"]
