from __future__ import annotations

from edgar_sec.domain.forms.common.processing import AcquisitionOperation
from edgar_sec.domain.forms.families.form_f3.processing import PROFILE_FORM_F3
from edgar_sec.domain.forms.families.form_f3.reports import FormF3Report


def test_form_f3_profile_properties() -> None:
    assert PROFILE_FORM_F3.family == "F-3"
    assert PROFILE_FORM_F3.version == "v1"
    assert PROFILE_FORM_F3.allowed_operations == frozenset(
        {
            AcquisitionOperation.RAW,
            AcquisitionOperation.RENDER_TO_TXT,
        }
    )
    assert PROFILE_FORM_F3.preferred_operation == AcquisitionOperation.RENDER_TO_TXT
    assert PROFILE_FORM_F3.report_class is FormF3Report
    assert PROFILE_FORM_F3.review_analyzer == "edgar_sec.engine.forms.form_f3.analysis"


def test_form_f3_profile_flags() -> None:
    assert PROFILE_FORM_F3.has_toc is True
    assert PROFILE_FORM_F3.has_sections is True
    assert PROFILE_FORM_F3.has_notes is True
    assert PROFILE_FORM_F3.has_xbrl is True
    assert PROFILE_FORM_F3.has_operation(AcquisitionOperation.RAW)
    assert not PROFILE_FORM_F3.has_operation(AcquisitionOperation.RENDER_TO_XML)
