"""Tests for the Form N-PORT processing profile."""

from edgar_sec.domain.forms.common.processing import AcquisitionOperation
from edgar_sec.domain.forms.families.form_nport.processing import PROFILE_NPORT
from edgar_sec.domain.forms.families.form_nport.reports import FormNPortReport
from edgar_sec.domain.forms.families.processing_profiles import get_family_profile


def test_nport_profile_operations() -> None:
    """Profile allows RAW + RENDER_TO_XML with XML preferred."""
    assert PROFILE_NPORT.family == "N-PORT"
    assert PROFILE_NPORT.allowed_operations == frozenset(
        {AcquisitionOperation.RAW, AcquisitionOperation.RENDER_TO_XML}
    )
    assert PROFILE_NPORT.preferred_operation == AcquisitionOperation.RENDER_TO_XML
    assert PROFILE_NPORT.report_class is FormNPortReport
    assert PROFILE_NPORT.review_analyzer == "edgar_sec.engine.forms.form_nport.analysis"


def test_nport_profile_registered() -> None:
    """The catalog resolves the N-PORT family to the registered profile."""
    assert get_family_profile("N-PORT") is PROFILE_NPORT
    assert get_family_profile("NPORT-P") is PROFILE_NPORT
