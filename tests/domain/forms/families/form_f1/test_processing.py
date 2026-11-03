from __future__ import annotations

from edgar_sec.domain.forms.common.processing import AcquisitionOperation
from edgar_sec.domain.forms.families.form_f1.processing import (
    PROFILE_FORM_F1,
    PROFILE_FORM_F2,
)
from edgar_sec.domain.forms.families.form_f1.reports import FormF1Report


def test_form_f1_profile_properties() -> None:
    assert PROFILE_FORM_F1.family == "F-1"
    assert PROFILE_FORM_F1.version == "v1"
    assert PROFILE_FORM_F1.allowed_operations == frozenset(
        {
            AcquisitionOperation.RAW,
            AcquisitionOperation.RENDER_TO_TXT,
        }
    )
    assert PROFILE_FORM_F1.preferred_operation == AcquisitionOperation.RENDER_TO_TXT
    assert PROFILE_FORM_F1.report_class is FormF1Report
    assert PROFILE_FORM_F1.review_analyzer == "edgar_sec.engine.forms.form_f1.analysis"


def test_form_f2_profile_is_the_variant_profile() -> None:
    assert PROFILE_FORM_F2.family == "F-2"
    assert PROFILE_FORM_F2.version == "v1"
    assert PROFILE_FORM_F2.report_class is FormF1Report
    assert PROFILE_FORM_F2.review_analyzer == PROFILE_FORM_F1.review_analyzer
    assert PROFILE_FORM_F2.allowed_operations == PROFILE_FORM_F1.allowed_operations


def test_form_f1_profile_flags() -> None:
    for profile in (PROFILE_FORM_F1, PROFILE_FORM_F2):
        assert profile.has_toc is True
        assert profile.has_sections is True
        assert profile.has_notes is True
        assert profile.has_xbrl is True
        assert profile.has_operation(AcquisitionOperation.RAW)
        assert not profile.has_operation(AcquisitionOperation.RENDER_TO_XML)
