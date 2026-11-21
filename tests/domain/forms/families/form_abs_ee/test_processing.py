from __future__ import annotations

from edgar_sec.domain.forms.common.processing import AcquisitionOperation
from edgar_sec.domain.forms.families.form_abs_ee.processing import PROFILE_ABS_EE
from edgar_sec.domain.forms.families.form_abs_ee.reports import AbsEeReport


def test_profile_is_companion_scope_xml() -> None:
    assert PROFILE_ABS_EE.family == "ABS-EE"
    assert PROFILE_ABS_EE.preferred_operation is AcquisitionOperation.RENDER_TO_XML
    assert PROFILE_ABS_EE.report_class is AbsEeReport
    assert (
        PROFILE_ABS_EE.review_analyzer == "edgar_sec.engine.forms.form_abs_ee.analysis"
    )
