"""Quarterly report family profiles for Form 10-Q."""

from __future__ import annotations

from edgar_sec.domain.forms.common.aliases import aliases_for_family
from edgar_sec.domain.forms.common.exhibits import PrimaryReportProfile
from edgar_sec.domain.forms.families.quarterly.evidence import QUARTERLY_REPORT_TITLES

PRIMARY_PROFILE_10Q = PrimaryReportProfile(
    family="10-Q",
    version="v1",
    statutory_titles=QUARTERLY_REPORT_TITLES,
    designator_tokens=aliases_for_family("10-Q"),
    commission_header_required=True,
    derived_taxonomy_family="quarterly",
    checkbox_schema_family="10-Q",
)

__all__ = [
    "PRIMARY_PROFILE_10Q",
]
