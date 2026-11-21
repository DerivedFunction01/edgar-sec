"""Tests for the N-CSR processing profile."""

from edgar_sec.domain.forms.common.processing import AcquisitionOperation
from edgar_sec.domain.forms.families.form_ncsr.processing import PROFILE_FORM_NCSR
from edgar_sec.domain.forms.families.form_ncsr.reports import FormNCsrReport
from edgar_sec.domain.forms.families.processing_profiles import get_family_profile


def test_profile_operations() -> None:
    """Profile allows RAW + RENDER_TO_TXT with text preferred."""
    assert PROFILE_FORM_NCSR.family == "N-CSR"
    assert PROFILE_FORM_NCSR.allowed_operations == frozenset(
        {AcquisitionOperation.RAW, AcquisitionOperation.RENDER_TO_TXT}
    )
    assert PROFILE_FORM_NCSR.preferred_operation == AcquisitionOperation.RENDER_TO_TXT
    assert PROFILE_FORM_NCSR.report_class is FormNCsrReport
    assert (
        PROFILE_FORM_NCSR.review_analyzer == "edgar_sec.engine.forms.form_ncsr.analysis"
    )


def test_profile_registered() -> None:
    """The catalog resolves the family to the registered profile."""
    assert get_family_profile("N-CSR") is PROFILE_FORM_NCSR
