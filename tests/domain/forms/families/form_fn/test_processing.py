from __future__ import annotations

from edgar_sec.domain.forms.common.processing import AcquisitionOperation
from edgar_sec.domain.forms.families.form_fn.processing import PROFILE_FORM_FN
from edgar_sec.domain.forms.families.form_fn.reports import FormFnReport


def test_form_fn_profile_properties() -> None:
    assert PROFILE_FORM_FN.family == "F-N"
    assert PROFILE_FORM_FN.version == "v1"
    assert PROFILE_FORM_FN.allowed_operations == frozenset(
        {
            AcquisitionOperation.RAW,
            AcquisitionOperation.RENDER_TO_TXT,
        }
    )
    assert PROFILE_FORM_FN.preferred_operation == AcquisitionOperation.RENDER_TO_TXT
    assert PROFILE_FORM_FN.report_class is FormFnReport
    assert PROFILE_FORM_FN.review_analyzer == "edgar_sec.engine.forms.form_fn.analysis"


def test_form_fn_profile_flags() -> None:
    assert PROFILE_FORM_FN.has_toc is False
    assert PROFILE_FORM_FN.has_sections is False
    assert PROFILE_FORM_FN.has_notes is False
    assert PROFILE_FORM_FN.has_xbrl is False
