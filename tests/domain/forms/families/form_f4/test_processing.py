from __future__ import annotations

from edgar_sec.domain.forms.common.processing import AcquisitionOperation
from edgar_sec.domain.forms.families.form_f4.processing import PROFILE_FORM_F4
from edgar_sec.domain.forms.families.form_f4.reports import FormF4Report


def test_form_f4_profile_properties() -> None:
    assert PROFILE_FORM_F4.family == "F-4"
    assert PROFILE_FORM_F4.version == "v1"
    assert PROFILE_FORM_F4.allowed_operations == frozenset(
        {
            AcquisitionOperation.RAW,
            AcquisitionOperation.RENDER_TO_TXT,
        }
    )
    assert PROFILE_FORM_F4.preferred_operation == AcquisitionOperation.RENDER_TO_TXT
    assert PROFILE_FORM_F4.report_class is FormF4Report
    assert PROFILE_FORM_F4.review_analyzer == "edgar_sec.engine.forms.form_f4.analysis"


def test_form_f4_profile_flags() -> None:
    assert PROFILE_FORM_F4.has_toc is True
    assert PROFILE_FORM_F4.has_sections is True
    assert PROFILE_FORM_F4.has_notes is True
    assert PROFILE_FORM_F4.has_xbrl is True
    assert PROFILE_FORM_F4.has_operation(AcquisitionOperation.RAW)
    assert not PROFILE_FORM_F4.has_operation(AcquisitionOperation.RENDER_TO_XML)
