"""Tests for the 40-17F1 processing profile."""

from edgar_sec.domain.forms.common.aliases import resolve_alias
from edgar_sec.domain.forms.common.processing import AcquisitionOperation
from edgar_sec.domain.forms.families.form_4017f1.processing import PROFILE_FORM_4017F1
from edgar_sec.domain.forms.families.form_4017f1.reports import Form4017F1Report
from edgar_sec.domain.forms.families.processing_profiles import get_family_profile


def test_profile_operations() -> None:
    """Profile allows RAW + RENDER_TO_TXT with text preferred."""
    assert PROFILE_FORM_4017F1.family == "40-17F1"
    assert PROFILE_FORM_4017F1.allowed_operations == frozenset(
        {AcquisitionOperation.RAW, AcquisitionOperation.RENDER_TO_TXT}
    )
    assert PROFILE_FORM_4017F1.preferred_operation == AcquisitionOperation.RENDER_TO_TXT
    assert PROFILE_FORM_4017F1.report_class is Form4017F1Report
    assert PROFILE_FORM_4017F1.review_analyzer is None
    assert PROFILE_FORM_4017F1.has_sections is True
    assert PROFILE_FORM_4017F1.has_xbrl is False


def test_profile_registered() -> None:
    """The catalog resolves the family and its amendment to the profile."""
    assert get_family_profile("40-17F1") is PROFILE_FORM_4017F1
    assert get_family_profile("40-17F1/A") is PROFILE_FORM_4017F1
    assert resolve_alias("40-17F1/A") == "40-17F1"
