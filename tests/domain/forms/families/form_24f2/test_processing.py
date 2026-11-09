"""Tests for the 24F-2 processing profile."""

from edgar_sec.domain.forms.common.processing import AcquisitionOperation
from edgar_sec.domain.forms.families.form_24f2.processing import PROFILE_FORM_24F2
from edgar_sec.domain.forms.families.form_24f2.reports import Form24F2Report
from edgar_sec.domain.forms.families.processing_profiles import get_family_profile


def test_profile_operations() -> None:
    """Profile allows RAW + RENDER_TO_TXT with text preferred."""
    assert PROFILE_FORM_24F2.family == "24F-2NT"
    assert PROFILE_FORM_24F2.allowed_operations == frozenset(
        {AcquisitionOperation.RAW, AcquisitionOperation.RENDER_TO_TXT}
    )
    assert PROFILE_FORM_24F2.preferred_operation == AcquisitionOperation.RENDER_TO_TXT
    assert PROFILE_FORM_24F2.report_class is Form24F2Report
    assert PROFILE_FORM_24F2.review_analyzer is None
    assert PROFILE_FORM_24F2.has_sections is True
    assert PROFILE_FORM_24F2.has_xbrl is False


def test_profile_registered() -> None:
    """The catalog resolves every code in the line to the profile."""
    for code in ("24F-2NT", "24F-2NT/A", "24F-2TM", "24F-2EL", "24F-2EL/A", "24F-1"):
        assert get_family_profile(code) is PROFILE_FORM_24F2
