from __future__ import annotations

from edgar_sec.domain.forms.families.form_12reg.processing import (
    PROFILE_FORM_8A,
    PROFILE_FORM_8B,
    PROFILE_FORM_25,
)
from edgar_sec.domain.forms.families.form_12reg.reports import Form12RegReport

_ANALYZER = "edgar_sec.engine.forms.form_12reg.analysis"


def test_profiles_share_one_analyzer() -> None:
    for profile, family in (
        (PROFILE_FORM_25, "25"),
        (PROFILE_FORM_8A, "8-A"),
        (PROFILE_FORM_8B, "8-B"),
    ):
        assert profile.family == family
        assert profile.review_analyzer == _ANALYZER
        assert profile.report_class is Form12RegReport


def test_notification_face_has_no_sections() -> None:
    assert PROFILE_FORM_25.has_sections is False
    assert PROFILE_FORM_8A.has_sections is True
