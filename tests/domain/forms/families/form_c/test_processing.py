from __future__ import annotations

from edgar_sec.domain.forms.common.processing import AcquisitionOperation
from edgar_sec.domain.forms.families.form_c.processing import PROFILE_FORM_C
from edgar_sec.domain.forms.families.form_c.reports import FormCReport


def test_profile_is_xml_only_with_xml_preferred() -> None:
    assert PROFILE_FORM_C.family == "C"
    assert PROFILE_FORM_C.preferred_operation is AcquisitionOperation.RENDER_TO_XML
    assert PROFILE_FORM_C.report_class is FormCReport
    assert PROFILE_FORM_C.review_analyzer == "edgar_sec.engine.forms.form_c.analysis"
