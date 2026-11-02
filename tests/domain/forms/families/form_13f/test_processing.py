"""Tests for the Form 13F processing profile."""

from edgar_sec.domain.forms.common.processing import AcquisitionOperation
from edgar_sec.domain.forms.families.form_13f.processing import PROFILE_FORM_13F
from edgar_sec.domain.forms.families.form_13f.reports import Form13FReport
from edgar_sec.domain.forms.families.processing_profiles import get_family_profile


def test_form13f_profile_operations() -> None:
    """Profile allows RAW + RENDER_TO_XML with XML preferred."""
    assert PROFILE_FORM_13F.family == "13F"
    assert PROFILE_FORM_13F.allowed_operations == frozenset(
        {AcquisitionOperation.RAW, AcquisitionOperation.RENDER_TO_XML}
    )
    assert PROFILE_FORM_13F.preferred_operation == AcquisitionOperation.RENDER_TO_XML
    assert PROFILE_FORM_13F.report_class is Form13FReport
    assert (
        PROFILE_FORM_13F.review_analyzer == "edgar_sec.engine.forms.form_13f.analysis"
    )


def test_form13f_profile_registered() -> None:
    """The catalog resolves the 13F family to the registered profile."""
    assert get_family_profile("13F") is PROFILE_FORM_13F
    assert get_family_profile("13F-HR") is PROFILE_FORM_13F
