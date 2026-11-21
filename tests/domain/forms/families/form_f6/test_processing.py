from __future__ import annotations

from edgar_sec.domain.forms.common.processing import AcquisitionOperation
from edgar_sec.domain.forms.families.form_f6.processing import PROFILE_FORM_F6
from edgar_sec.domain.forms.families.form_f6.reports import FormF6Report


def test_form_f6_profile_properties() -> None:
    assert PROFILE_FORM_F6.family == "F-6"
    assert PROFILE_FORM_F6.version == "v1"
    assert PROFILE_FORM_F6.allowed_operations == frozenset(
        {
            AcquisitionOperation.RAW,
            AcquisitionOperation.RENDER_TO_TXT,
        }
    )
    assert PROFILE_FORM_F6.preferred_operation == AcquisitionOperation.RENDER_TO_TXT
    assert PROFILE_FORM_F6.report_class is FormF6Report
    assert PROFILE_FORM_F6.review_analyzer == "edgar_sec.engine.forms.form_f6.analysis"


def test_form_f6_profile_flags() -> None:
    assert PROFILE_FORM_F6.has_toc is False
    assert PROFILE_FORM_F6.has_sections is True
    assert PROFILE_FORM_F6.has_notes is False
    assert PROFILE_FORM_F6.has_xbrl is False
    assert not PROFILE_FORM_F6.has_operation(AcquisitionOperation.RENDER_TO_XML)
