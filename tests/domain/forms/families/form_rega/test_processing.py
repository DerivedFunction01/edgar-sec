from __future__ import annotations

from edgar_sec.domain.forms.common.processing import AcquisitionOperation
from edgar_sec.domain.forms.families.form_rega.processing import (
    PROFILE_REGA_ANNUAL,
    PROFILE_REGA_CURRENT,
    PROFILE_REGA_EXIT,
    PROFILE_REGA_OFFERING,
    PROFILE_REGA_SEMI_ANNUAL,
)
from edgar_sec.domain.forms.families.form_rega.reports import RegAReport

_ANALYZER = "edgar_sec.engine.forms.form_rega.analysis"


def test_xml_profiles_prefer_xml() -> None:
    for profile, family in (
        (PROFILE_REGA_OFFERING, "1-A"),
        (PROFILE_REGA_ANNUAL, "1-K"),
        (PROFILE_REGA_EXIT, "1-Z"),
    ):
        assert profile.family == family
        assert profile.preferred_operation is AcquisitionOperation.RENDER_TO_XML
        assert AcquisitionOperation.RENDER_TO_XML in profile.allowed_operations
        assert profile.report_class is RegAReport
        assert profile.review_analyzer == _ANALYZER


def test_offering_profile_also_renders_text_for_withdrawal_letters() -> None:
    assert (
        AcquisitionOperation.RENDER_TO_TXT in PROFILE_REGA_OFFERING.allowed_operations
    )


def test_exit_profile_also_renders_text_for_withdrawal_letters() -> None:
    assert AcquisitionOperation.RENDER_TO_TXT in PROFILE_REGA_EXIT.allowed_operations


def test_text_profiles_prefer_text_with_sections() -> None:
    for profile, family in (
        (PROFILE_REGA_SEMI_ANNUAL, "1-SA"),
        (PROFILE_REGA_CURRENT, "1-U"),
    ):
        assert profile.family == family
        assert profile.preferred_operation is AcquisitionOperation.RENDER_TO_TXT
        assert profile.allowed_operations == frozenset(
            {AcquisitionOperation.RAW, AcquisitionOperation.RENDER_TO_TXT}
        )
        assert profile.has_sections
        assert profile.report_class is RegAReport
        assert profile.review_analyzer == _ANALYZER
