from __future__ import annotations

from edgar_sec.domain.forms.common.processing import AcquisitionOperation
from edgar_sec.domain.forms.families.form_12b25.processing import PROFILE_FORM_12B25
from edgar_sec.domain.forms.families.form_12b25.reports import Form12B25Report


def test_form_12b25_profile_properties() -> None:
    assert PROFILE_FORM_12B25.family == "12B-25"
    assert PROFILE_FORM_12B25.version == "v1"
    assert PROFILE_FORM_12B25.allowed_operations == frozenset(
        {
            AcquisitionOperation.RAW,
            AcquisitionOperation.RENDER_TO_TXT,
        }
    )
    assert PROFILE_FORM_12B25.preferred_operation == AcquisitionOperation.RENDER_TO_TXT
    assert PROFILE_FORM_12B25.report_class is Form12B25Report
    assert (
        PROFILE_FORM_12B25.review_analyzer
        == "edgar_sec.engine.forms.form_12b25.analysis"
    )


def test_form_12b25_profile_flags() -> None:
    assert PROFILE_FORM_12B25.has_toc is False
    assert PROFILE_FORM_12B25.has_sections is True
    assert PROFILE_FORM_12B25.has_notes is False
    assert PROFILE_FORM_12B25.has_xbrl is False


def test_form_12b25_profile_operations() -> None:
    assert PROFILE_FORM_12B25.has_operation(AcquisitionOperation.RAW)
    assert PROFILE_FORM_12B25.has_operation(AcquisitionOperation.RENDER_TO_TXT)
    assert not PROFILE_FORM_12B25.has_operation(AcquisitionOperation.RENDER_TO_XML)
