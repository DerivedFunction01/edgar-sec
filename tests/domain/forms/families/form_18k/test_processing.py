"""Tests for the 18-K processing profile."""

from edgar_sec.domain.forms.common.processing import AcquisitionOperation
from edgar_sec.domain.forms.families.form_18k.processing import PROFILE_FORM_18K
from edgar_sec.domain.forms.families.form_18k.reports import Form18KReport
from edgar_sec.domain.forms.families.processing_profiles import get_family_profile


def test_profile_operations() -> None:
    """Profile allows RAW + RENDER_TO_TXT with text preferred."""
    assert PROFILE_FORM_18K.family == "18-K"
    assert PROFILE_FORM_18K.allowed_operations == frozenset(
        {AcquisitionOperation.RAW, AcquisitionOperation.RENDER_TO_TXT}
    )
    assert PROFILE_FORM_18K.preferred_operation == AcquisitionOperation.RENDER_TO_TXT
    assert PROFILE_FORM_18K.report_class is Form18KReport
    assert PROFILE_FORM_18K.review_analyzer is None
    assert PROFILE_FORM_18K.has_sections is True
    assert PROFILE_FORM_18K.has_xbrl is False


def test_profile_registered() -> None:
    """The catalog resolves the family and its amendment to the profile."""
    assert get_family_profile("18-K") is PROFILE_FORM_18K
    assert get_family_profile("18-K/A") is PROFILE_FORM_18K
