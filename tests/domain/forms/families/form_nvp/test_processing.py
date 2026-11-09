"""Tests for the N-VP processing profile."""

from edgar_sec.domain.forms.common.processing import AcquisitionOperation
from edgar_sec.domain.forms.families.form_nvp.processing import PROFILE_FORM_NVP
from edgar_sec.domain.forms.families.form_nvp.reports import FormNVPReport
from edgar_sec.domain.forms.families.processing_profiles import get_family_profile


def test_profile_operations() -> None:
    """Profile allows RAW + RENDER_TO_TXT with text preferred."""
    assert PROFILE_FORM_NVP.family == "N-VP"
    assert PROFILE_FORM_NVP.allowed_operations == frozenset(
        {AcquisitionOperation.RAW, AcquisitionOperation.RENDER_TO_TXT}
    )
    assert PROFILE_FORM_NVP.preferred_operation == AcquisitionOperation.RENDER_TO_TXT
    assert PROFILE_FORM_NVP.report_class is FormNVPReport
    assert PROFILE_FORM_NVP.review_analyzer is None
    assert PROFILE_FORM_NVP.has_sections is True
    assert PROFILE_FORM_NVP.has_xbrl is False


def test_profile_registered() -> None:
    """The catalog resolves the family and its members to the profile."""
    assert get_family_profile("N-VP") is PROFILE_FORM_NVP
    assert get_family_profile("N-VP/A") is PROFILE_FORM_NVP
    assert get_family_profile("N-VPFS") is PROFILE_FORM_NVP
    assert get_family_profile("N-VPFS/A") is PROFILE_FORM_NVP
