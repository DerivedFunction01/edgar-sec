"""Annual report family profiles for Form 10-K and Form 20-F."""

from __future__ import annotations

from edgar_sec.domain.forms.common.aliases import aliases_for_family
from edgar_sec.domain.forms.common.exhibits import PrimaryReportProfile
from edgar_sec.domain.forms.families.annual.evidence import ANNUAL_REPORT_TITLES

PRIMARY_PROFILE_10K = PrimaryReportProfile(
    family="10-K",
    version="v1",
    statutory_titles=ANNUAL_REPORT_TITLES,
    designator_tokens=aliases_for_family("10-K"),
    commission_header_required=True,
    derived_taxonomy_family="annual",
    checkbox_schema_family="10-K",
)

PRIMARY_PROFILE_20F = PrimaryReportProfile(
    family="20-F",
    version="v1",
    statutory_titles=ANNUAL_REPORT_TITLES,
    designator_tokens=aliases_for_family("20-F"),
    commission_header_required=True,
    derived_taxonomy_family="annual",
    checkbox_schema_family=None,
)

__all__ = [
    "PRIMARY_PROFILE_10K",
    "PRIMARY_PROFILE_20F",
]
