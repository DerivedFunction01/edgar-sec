"""DRS wrapper primary-report profile: the banner and the submission
designator identify the primary, not a commission header or a title of
its own — the face inside is the base form's.
"""

from __future__ import annotations

from edgar_sec.domain.forms.common.aliases import aliases_for_family
from edgar_sec.domain.forms.common.exhibits import PrimaryReportProfile

PRIMARY_PROFILE_DRS = PrimaryReportProfile(
    family="DRS",
    version="v1",
    statutory_titles=("as confidentially submitted",),
    designator_tokens=aliases_for_family("DRS"),
    commission_header_required=False,
)

__all__ = ["PRIMARY_PROFILE_DRS"]
