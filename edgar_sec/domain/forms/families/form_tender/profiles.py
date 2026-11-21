"""Tender family primary-report profile for the merged schedule lines."""

from __future__ import annotations

from edgar_sec.domain.forms.common.aliases import aliases_for_family
from edgar_sec.domain.forms.common.exhibits import PrimaryReportProfile
from edgar_sec.domain.forms.families.form_tender.taxonomy import TENDER_TITLES

PRIMARY_PROFILE_TENDER = PrimaryReportProfile(
    family="SC TO",
    version="v1",
    statutory_titles=TENDER_TITLES,
    designator_tokens=aliases_for_family("SC TO"),
    commission_header_required=True,
)

__all__ = ["PRIMARY_PROFILE_TENDER"]
