"""Current report family profiles for Form 8-K."""

from __future__ import annotations

from edgar_sec.domain.forms.common.aliases import aliases_for_family
from edgar_sec.domain.forms.common.exhibits import PrimaryReportProfile
from edgar_sec.domain.forms.families.current.evidence import CURRENT_TITLES

PRIMARY_PROFILE_8K = PrimaryReportProfile(
    family="8-K",
    version="v1",
    statutory_titles=CURRENT_TITLES,
    designator_tokens=aliases_for_family("8-K"),
    commission_header_required=True,
)

__all__ = [
    "PRIMARY_PROFILE_8K",
]
