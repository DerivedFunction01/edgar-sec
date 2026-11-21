"""Tests for the 40-APP processing profile."""

from edgar_sec.domain.forms.common.processing import AcquisitionOperation
from edgar_sec.domain.forms.families.form_40app.processing import PROFILE_FORM_40APP
from edgar_sec.domain.forms.families.form_40app.reports import Form40AppReport
from edgar_sec.domain.forms.families.processing_profiles import get_family_profile


def test_profile_operations() -> None:
    """Profile allows RAW + RENDER_TO_TXT with text preferred."""
    assert PROFILE_FORM_40APP.family == "40-APP"
    assert PROFILE_FORM_40APP.allowed_operations == frozenset(
        {AcquisitionOperation.RAW, AcquisitionOperation.RENDER_TO_TXT}
    )
    assert PROFILE_FORM_40APP.preferred_operation == AcquisitionOperation.RENDER_TO_TXT
    assert PROFILE_FORM_40APP.report_class is Form40AppReport
    assert PROFILE_FORM_40APP.review_analyzer is None
    assert PROFILE_FORM_40APP.has_sections is True
    assert PROFILE_FORM_40APP.has_xbrl is False


def test_profile_registered() -> None:
    """The catalog resolves the family and its amendment to the profile."""
    assert get_family_profile("40-APP") is PROFILE_FORM_40APP
    assert get_family_profile("40-APP/A") is PROFILE_FORM_40APP
