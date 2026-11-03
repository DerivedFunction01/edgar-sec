"""Tests for the Form N-PX processing profile."""

from edgar_sec.domain.forms.common.processing import AcquisitionOperation
from edgar_sec.domain.forms.families.form_npx.processing import PROFILE_N_PX
from edgar_sec.domain.forms.families.form_npx.reports import FormNPxReport
from edgar_sec.domain.forms.families.processing_profiles import get_family_profile


def test_npx_profile_operations() -> None:
    """Profile allows RAW + RENDER_TO_XML with XML preferred."""
    assert PROFILE_N_PX.family == "N-PX"
    assert PROFILE_N_PX.allowed_operations == frozenset(
        {AcquisitionOperation.RAW, AcquisitionOperation.RENDER_TO_XML}
    )
    assert PROFILE_N_PX.preferred_operation == AcquisitionOperation.RENDER_TO_XML
    assert PROFILE_N_PX.report_class is FormNPxReport
    assert PROFILE_N_PX.review_analyzer == "edgar_sec.engine.forms.form_npx.analysis"


def test_npx_profile_registered() -> None:
    """The catalog resolves the N-PX family to the registered profile."""
    assert get_family_profile("N-PX") is PROFILE_N_PX
    assert get_family_profile("N-PX CTR") is PROFILE_N_PX
