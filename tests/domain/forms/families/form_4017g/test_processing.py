"""Tests for the 40-17G processing profile."""

from edgar_sec.domain.forms.common.processing import AcquisitionOperation
from edgar_sec.domain.forms.families.form_4017g.processing import PROFILE_FORM_4017G
from edgar_sec.domain.forms.families.form_4017g.reports import Form4017GReport
from edgar_sec.domain.forms.families.processing_profiles import get_family_profile


def test_profile_operations() -> None:
    """Profile allows RAW + RENDER_TO_TXT with text preferred."""
    assert PROFILE_FORM_4017G.family == "40-17G"
    assert PROFILE_FORM_4017G.allowed_operations == frozenset(
        {AcquisitionOperation.RAW, AcquisitionOperation.RENDER_TO_TXT}
    )
    assert PROFILE_FORM_4017G.preferred_operation == AcquisitionOperation.RENDER_TO_TXT
    assert PROFILE_FORM_4017G.report_class is Form4017GReport
    assert PROFILE_FORM_4017G.review_analyzer is None
    assert PROFILE_FORM_4017G.has_sections is True
    assert PROFILE_FORM_4017G.has_xbrl is False


def test_profile_registered() -> None:
    """The catalog resolves the family and its members to the profile."""
    assert get_family_profile("40-17G") is PROFILE_FORM_4017G
    assert get_family_profile("40-17G/A") is PROFILE_FORM_4017G
    assert get_family_profile("40-17GCS") is PROFILE_FORM_4017G
