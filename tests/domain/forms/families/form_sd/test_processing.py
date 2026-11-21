from __future__ import annotations

from edgar_sec.domain.forms.common.processing import AcquisitionOperation
from edgar_sec.domain.forms.families.form_sd.processing import PROFILE_SD
from edgar_sec.domain.forms.families.form_sd.reports import FormSDReport

_ANALYZER = "edgar_sec.engine.forms.form_sd.analysis"


def test_profile_wiring() -> None:
    assert PROFILE_SD.family == "SD"
    assert PROFILE_SD.review_analyzer == _ANALYZER
    assert PROFILE_SD.report_class is FormSDReport
    assert PROFILE_SD.preferred_operation is AcquisitionOperation.RENDER_TO_TXT


def test_profile_shape() -> None:
    assert PROFILE_SD.has_sections is True
    assert PROFILE_SD.has_xbrl is False
    assert PROFILE_SD.has_notes is False
