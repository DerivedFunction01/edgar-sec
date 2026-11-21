from __future__ import annotations

from edgar_sec.domain.forms.common.processing import AcquisitionOperation
from edgar_sec.domain.forms.families.form_15.processing import PROFILE_FORM_15
from edgar_sec.domain.forms.families.form_15.reports import Form15Report


def test_form_15_profile_properties() -> None:
    assert PROFILE_FORM_15.family == "15"
    assert PROFILE_FORM_15.version == "v1"
    assert PROFILE_FORM_15.allowed_operations == frozenset(
        {
            AcquisitionOperation.RAW,
            AcquisitionOperation.RENDER_TO_TXT,
        }
    )
    assert PROFILE_FORM_15.preferred_operation == AcquisitionOperation.RENDER_TO_TXT
    assert PROFILE_FORM_15.report_class is Form15Report
    assert PROFILE_FORM_15.review_analyzer == "edgar_sec.engine.forms.form_15.analysis"


def test_form_15_profile_flags() -> None:
    assert PROFILE_FORM_15.has_toc is False
    assert PROFILE_FORM_15.has_sections is False
    assert PROFILE_FORM_15.has_notes is False
    assert PROFILE_FORM_15.has_xbrl is False


def test_form_15_profile_operations() -> None:
    assert PROFILE_FORM_15.has_operation(AcquisitionOperation.RAW)
    assert PROFILE_FORM_15.has_operation(AcquisitionOperation.RENDER_TO_TXT)
    assert not PROFILE_FORM_15.has_operation(AcquisitionOperation.RENDER_TO_XML)
