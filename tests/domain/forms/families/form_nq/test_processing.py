"""Tests for the N-Q processing profile."""

from edgar_sec.domain.forms.common.processing import AcquisitionOperation
from edgar_sec.domain.forms.families.form_nq.processing import PROFILE_FORM_NQ
from edgar_sec.domain.forms.families.form_nq.reports import FormNQReport
from edgar_sec.domain.forms.families.processing_profiles import get_family_profile


def test_profile_operations() -> None:
    """Profile allows RAW + RENDER_TO_TXT with text preferred."""
    assert PROFILE_FORM_NQ.family == "N-Q"
    assert PROFILE_FORM_NQ.allowed_operations == frozenset(
        {AcquisitionOperation.RAW, AcquisitionOperation.RENDER_TO_TXT}
    )
    assert PROFILE_FORM_NQ.preferred_operation == AcquisitionOperation.RENDER_TO_TXT
    assert PROFILE_FORM_NQ.report_class is FormNQReport
    assert PROFILE_FORM_NQ.review_analyzer == "edgar_sec.engine.forms.form_nq.analysis"


def test_profile_registered() -> None:
    """The catalog resolves the family to the registered profile."""
    assert get_family_profile("N-Q") is PROFILE_FORM_NQ
