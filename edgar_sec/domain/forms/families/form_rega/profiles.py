"""Reg A text-report primary profiles: the statutory report titles and
the form designators identify the primary; 1-A-W letters carry neither
and stay on the generic profile.
"""

from __future__ import annotations

from edgar_sec.domain.forms.common.aliases import aliases_for_family
from edgar_sec.domain.forms.common.exhibits import PrimaryReportProfile
from edgar_sec.domain.forms.families.form_rega.taxonomy import (
    FORM_1SA_TITLES,
    FORM_1U_TITLES,
)

PRIMARY_PROFILE_1SA = PrimaryReportProfile(
    family="1-SA",
    version="v1",
    statutory_titles=FORM_1SA_TITLES,
    designator_tokens=aliases_for_family("1-SA"),
    commission_header_required=True,
)

PRIMARY_PROFILE_1U = PrimaryReportProfile(
    family="1-U",
    version="v1",
    statutory_titles=FORM_1U_TITLES,
    designator_tokens=aliases_for_family("1-U"),
    commission_header_required=True,
)

__all__ = ["PRIMARY_PROFILE_1SA", "PRIMARY_PROFILE_1U"]
