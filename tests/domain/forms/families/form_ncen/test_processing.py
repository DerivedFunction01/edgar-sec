"""Tests for the Form N-CEN processing profile."""

from edgar_sec.domain.forms.common.processing import AcquisitionOperation
from edgar_sec.domain.forms.families.form_ncen.processing import PROFILE_N_CEN
from edgar_sec.domain.forms.families.form_ncen.reports import FormNCenReport
from edgar_sec.domain.forms.families.processing_profiles import get_family_profile


def test_ncen_profile_operations() -> None:
    """Profile allows RAW + RENDER_TO_XML with XML preferred."""
    assert PROFILE_N_CEN.family == "N-CEN"
    assert PROFILE_N_CEN.allowed_operations == frozenset(
        {AcquisitionOperation.RAW, AcquisitionOperation.RENDER_TO_XML}
    )
    assert PROFILE_N_CEN.preferred_operation == AcquisitionOperation.RENDER_TO_XML
    assert PROFILE_N_CEN.report_class is FormNCenReport
    assert PROFILE_N_CEN.review_analyzer == "edgar_sec.engine.forms.form_ncen.analysis"


def test_ncen_profile_registered() -> None:
    """The catalog resolves the N-CEN family to the registered profile."""
    assert get_family_profile("N-CEN") is PROFILE_N_CEN
    assert get_family_profile("N-CEN/A") is PROFILE_N_CEN
