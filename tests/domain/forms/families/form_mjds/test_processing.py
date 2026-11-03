from __future__ import annotations

from edgar_sec.domain.forms.common.processing import AcquisitionOperation
from edgar_sec.domain.forms.families.form_mjds.processing import (
    PROFILE_FORM_F7,
    PROFILE_FORM_F8,
    PROFILE_FORM_F9,
    PROFILE_FORM_F10,
    PROFILE_FORM_F80,
)
from edgar_sec.domain.forms.families.form_mjds.reports import FormMjdsReport

_PROFILES = (
    PROFILE_FORM_F7,
    PROFILE_FORM_F8,
    PROFILE_FORM_F9,
    PROFILE_FORM_F10,
    PROFILE_FORM_F80,
)


def test_mjds_profiles_share_one_cover_posture() -> None:
    assert [p.family for p in _PROFILES] == ["F-7", "F-8", "F-9", "F-10", "F-80"]
    for profile in _PROFILES:
        assert profile.version == "v1"
        assert profile.report_class is FormMjdsReport
        assert profile.review_analyzer == "edgar_sec.engine.forms.form_mjds.analysis"
        assert profile.allowed_operations == frozenset(
            {
                AcquisitionOperation.RAW,
                AcquisitionOperation.RENDER_TO_TXT,
            }
        )
        assert profile.preferred_operation == AcquisitionOperation.RENDER_TO_TXT
        assert profile.has_toc is True
        assert profile.has_sections is True
        assert profile.has_notes is True
        assert profile.has_xbrl is True
