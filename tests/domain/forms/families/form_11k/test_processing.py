from __future__ import annotations

from edgar_sec.domain.forms.common.processing import AcquisitionOperation
from edgar_sec.domain.forms.families.form_11k.processing import PROFILE_FORM_11K
from edgar_sec.domain.forms.families.form_11k.reports import Form11KReport


def test_form_11k_profile_properties() -> None:
    assert PROFILE_FORM_11K.family == "11-K"
    assert PROFILE_FORM_11K.version == "v1"
    assert PROFILE_FORM_11K.allowed_operations == frozenset(
        {
            AcquisitionOperation.RAW,
            AcquisitionOperation.RENDER_TO_TXT,
        }
    )
    assert PROFILE_FORM_11K.preferred_operation == AcquisitionOperation.RENDER_TO_TXT
    assert PROFILE_FORM_11K.report_class is Form11KReport
    assert (
        PROFILE_FORM_11K.review_analyzer == "edgar_sec.engine.forms.form_11k.analysis"
    )


def test_form_11k_profile_flags() -> None:
    assert PROFILE_FORM_11K.has_toc is True
    assert PROFILE_FORM_11K.has_sections is True
    assert PROFILE_FORM_11K.has_notes is False
    assert PROFILE_FORM_11K.has_xbrl is False


def test_form_11k_profile_operations() -> None:
    assert PROFILE_FORM_11K.has_operation(AcquisitionOperation.RAW)
    assert PROFILE_FORM_11K.has_operation(AcquisitionOperation.RENDER_TO_TXT)
    assert not PROFILE_FORM_11K.has_operation(AcquisitionOperation.RENDER_TO_XML)
