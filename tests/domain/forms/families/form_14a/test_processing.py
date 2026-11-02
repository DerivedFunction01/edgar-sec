from __future__ import annotations

from edgar_sec.domain.forms.common.processing import AcquisitionOperation
from edgar_sec.domain.forms.families.form_14a.processing import PROFILE_FORM_14A
from edgar_sec.domain.forms.families.form_14a.reports import Form14AReport


def test_form_14a_profile_properties() -> None:
    assert PROFILE_FORM_14A.family == "14A"
    assert PROFILE_FORM_14A.version == "v1"
    assert PROFILE_FORM_14A.allowed_operations == frozenset(
        {
            AcquisitionOperation.RAW,
            AcquisitionOperation.RENDER_TO_TXT,
        }
    )
    assert PROFILE_FORM_14A.preferred_operation == AcquisitionOperation.RENDER_TO_TXT
    assert PROFILE_FORM_14A.report_class is Form14AReport
    assert (
        PROFILE_FORM_14A.review_analyzer == "edgar_sec.engine.forms.form_14a.analysis"
    )


def test_form_14a_profile_flags() -> None:
    assert PROFILE_FORM_14A.has_toc is True
    assert PROFILE_FORM_14A.has_sections is True
    assert PROFILE_FORM_14A.has_notes is False
    assert PROFILE_FORM_14A.has_xbrl is False


def test_form_14a_profile_operations() -> None:
    assert PROFILE_FORM_14A.has_operation(AcquisitionOperation.RAW)
    assert PROFILE_FORM_14A.has_operation(AcquisitionOperation.RENDER_TO_TXT)
    assert not PROFILE_FORM_14A.has_operation(AcquisitionOperation.RENDER_TO_XML)
