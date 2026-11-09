"""Tests for the 40-17F2 processing profile."""

from edgar_sec.domain.forms.common.processing import AcquisitionOperation
from edgar_sec.domain.forms.families.form_4017f2.processing import PROFILE_FORM_4017F2
from edgar_sec.domain.forms.families.form_4017f2.reports import Form4017F2Report
from edgar_sec.domain.forms.families.processing_profiles import get_family_profile


def test_profile_operations() -> None:
    """Profile allows RAW + RENDER_TO_TXT with text preferred."""
    assert PROFILE_FORM_4017F2.family == "40-17F2"
    assert PROFILE_FORM_4017F2.allowed_operations == frozenset(
        {AcquisitionOperation.RAW, AcquisitionOperation.RENDER_TO_TXT}
    )
    assert PROFILE_FORM_4017F2.preferred_operation == AcquisitionOperation.RENDER_TO_TXT
    assert PROFILE_FORM_4017F2.report_class is Form4017F2Report
    assert PROFILE_FORM_4017F2.review_analyzer is None
    assert PROFILE_FORM_4017F2.has_sections is True
    assert PROFILE_FORM_4017F2.has_xbrl is False


def test_profile_registered() -> None:
    """The catalog resolves the family and its amendment to the profile."""
    assert get_family_profile("40-17F2") is PROFILE_FORM_4017F2
    assert get_family_profile("40-17F2/A") is PROFILE_FORM_4017F2
