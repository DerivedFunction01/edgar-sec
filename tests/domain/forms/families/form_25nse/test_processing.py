from __future__ import annotations

from edgar_sec.domain.forms.common.processing import AcquisitionOperation
from edgar_sec.domain.forms.families.form_25nse.processing import PROFILE_FORM_25NSE
from edgar_sec.domain.forms.families.form_25nse.reports import Form25NseReport


def test_profile_is_xml_only_with_xml_preferred() -> None:
    assert PROFILE_FORM_25NSE.family == "25-NSE"
    assert PROFILE_FORM_25NSE.preferred_operation is AcquisitionOperation.RENDER_TO_XML
    assert PROFILE_FORM_25NSE.allowed_operations == frozenset(
        {AcquisitionOperation.RAW, AcquisitionOperation.RENDER_TO_XML}
    )
    assert PROFILE_FORM_25NSE.report_class is Form25NseReport
    assert (
        PROFILE_FORM_25NSE.review_analyzer
        == "edgar_sec.engine.forms.form_25nse.analysis"
    )
