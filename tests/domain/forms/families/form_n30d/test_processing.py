"""Tests for the N-30D processing profile."""

from edgar_sec.domain.forms.common.processing import AcquisitionOperation
from edgar_sec.domain.forms.families.form_n30d.processing import PROFILE_FORM_N30D
from edgar_sec.domain.forms.families.form_n30d.reports import FormN30DReport
from edgar_sec.domain.forms.families.processing_profiles import get_family_profile


def test_profile_operations() -> None:
    """Profile allows RAW + RENDER_TO_TXT with text preferred."""
    assert PROFILE_FORM_N30D.family == "N-30D"
    assert PROFILE_FORM_N30D.allowed_operations == frozenset(
        {AcquisitionOperation.RAW, AcquisitionOperation.RENDER_TO_TXT}
    )
    assert PROFILE_FORM_N30D.preferred_operation == AcquisitionOperation.RENDER_TO_TXT
    assert PROFILE_FORM_N30D.report_class is FormN30DReport
    assert PROFILE_FORM_N30D.review_analyzer is None
    assert PROFILE_FORM_N30D.has_sections is True
    assert PROFILE_FORM_N30D.has_xbrl is False


def test_profile_registered() -> None:
    """The catalog resolves the family, its amendment, and N-30B-2."""
    assert get_family_profile("N-30D") is PROFILE_FORM_N30D
    assert get_family_profile("N-30D/A") is PROFILE_FORM_N30D
    assert get_family_profile("N-30B-2") is PROFILE_FORM_N30D
