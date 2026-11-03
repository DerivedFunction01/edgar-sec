"""Tests for the 497 processing profile."""

from edgar_sec.domain.forms.common.processing import AcquisitionOperation
from edgar_sec.domain.forms.families.form_497.processing import PROFILE_FORM_497
from edgar_sec.domain.forms.families.form_497.reports import Form497Report
from edgar_sec.domain.forms.families.processing_profiles import get_family_profile


def test_profile_operations() -> None:
    """Profile allows RAW + RENDER_TO_TXT with text preferred."""
    assert PROFILE_FORM_497.family == "497"
    assert PROFILE_FORM_497.allowed_operations == frozenset(
        {AcquisitionOperation.RAW, AcquisitionOperation.RENDER_TO_TXT}
    )
    assert PROFILE_FORM_497.preferred_operation == AcquisitionOperation.RENDER_TO_TXT
    assert PROFILE_FORM_497.report_class is Form497Report
    assert (
        PROFILE_FORM_497.review_analyzer == "edgar_sec.engine.forms.form_497.analysis"
    )


def test_profile_registered() -> None:
    """The catalog resolves the family to the registered profile."""
    assert get_family_profile("497") is PROFILE_FORM_497
