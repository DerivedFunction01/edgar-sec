from __future__ import annotations

from edgar_sec.domain.forms.common.processing import AcquisitionOperation
from edgar_sec.domain.forms.families.form_abs_reports.processing import (
    PROFILE_ABS_REPORTS,
)
from edgar_sec.domain.forms.families.form_abs_reports.reports import (
    FormAbsReportsReport,
)

_ANALYZER = "edgar_sec.engine.forms.form_abs_reports.analysis"


def test_profile_registers_both_faces_under_the_abs_family() -> None:
    assert PROFILE_ABS_REPORTS.family == "ABS"
    assert PROFILE_ABS_REPORTS.review_analyzer == _ANALYZER
    assert PROFILE_ABS_REPORTS.report_class is FormAbsReportsReport
    assert PROFILE_ABS_REPORTS.has_sections is True
    assert PROFILE_ABS_REPORTS.preferred_operation is (
        AcquisitionOperation.RENDER_TO_TXT
    )
