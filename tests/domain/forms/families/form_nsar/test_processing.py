"""Tests for the NSAR processing profile."""

from edgar_sec.domain.forms.common.processing import AcquisitionOperation
from edgar_sec.domain.forms.families.form_nsar.processing import PROFILE_FORM_NSAR
from edgar_sec.domain.forms.families.form_nsar.reports import FormNSARReport
from edgar_sec.domain.forms.families.processing_profiles import get_family_profile


def test_profile_operations() -> None:
    """Profile allows RAW + RENDER_TO_TXT with text preferred."""
    assert PROFILE_FORM_NSAR.family == "NSAR"
    assert PROFILE_FORM_NSAR.allowed_operations == frozenset(
        {AcquisitionOperation.RAW, AcquisitionOperation.RENDER_TO_TXT}
    )
    assert PROFILE_FORM_NSAR.preferred_operation == AcquisitionOperation.RENDER_TO_TXT
    assert PROFILE_FORM_NSAR.report_class is FormNSARReport
    assert (
        PROFILE_FORM_NSAR.review_analyzer == "edgar_sec.engine.forms.form_nsar.analysis"
    )


def test_profile_registered() -> None:
    """The catalog resolves the family to the registered profile."""
    assert get_family_profile("NSAR") is PROFILE_FORM_NSAR
