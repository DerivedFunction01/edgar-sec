"""Tests for the Form N-MFP processing profile."""

from edgar_sec.domain.forms.common.processing import AcquisitionOperation
from edgar_sec.domain.forms.families.form_nmfp.processing import PROFILE_N_MFP
from edgar_sec.domain.forms.families.form_nmfp.reports import FormNMfpReport
from edgar_sec.domain.forms.families.processing_profiles import get_family_profile


def test_nmfp_profile_operations() -> None:
    """Profile allows RAW + RENDER_TO_XML with XML preferred."""
    assert PROFILE_N_MFP.family == "N-MFP"
    assert PROFILE_N_MFP.allowed_operations == frozenset(
        {AcquisitionOperation.RAW, AcquisitionOperation.RENDER_TO_XML}
    )
    assert PROFILE_N_MFP.preferred_operation == AcquisitionOperation.RENDER_TO_XML
    assert PROFILE_N_MFP.report_class is FormNMfpReport
    assert PROFILE_N_MFP.review_analyzer == "edgar_sec.engine.forms.form_nmfp.analysis"


def test_nmfp_profile_registered() -> None:
    """The catalog resolves the N-MFP family to the registered profile."""
    assert get_family_profile("N-MFP") is PROFILE_N_MFP
    assert get_family_profile("N-MFP3") is PROFILE_N_MFP
