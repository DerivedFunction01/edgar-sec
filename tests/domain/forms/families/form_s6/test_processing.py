"""Tests for the S-6 processing profile."""

from edgar_sec.domain.forms.common.aliases import resolve_alias
from edgar_sec.domain.forms.common.processing import AcquisitionOperation
from edgar_sec.domain.forms.families.form_s6.processing import PROFILE_FORM_S6
from edgar_sec.domain.forms.families.form_s6.reports import FormS6Report
from edgar_sec.domain.forms.families.processing_profiles import get_family_profile


def test_profile_operations() -> None:
    """Profile allows RAW + RENDER_TO_TXT with text preferred."""
    assert PROFILE_FORM_S6.family == "S-6"
    assert PROFILE_FORM_S6.allowed_operations == frozenset(
        {AcquisitionOperation.RAW, AcquisitionOperation.RENDER_TO_TXT}
    )
    assert PROFILE_FORM_S6.preferred_operation == AcquisitionOperation.RENDER_TO_TXT
    assert PROFILE_FORM_S6.report_class is FormS6Report
    assert PROFILE_FORM_S6.review_analyzer is None
    assert PROFILE_FORM_S6.has_sections is True
    assert PROFILE_FORM_S6.has_xbrl is False


def test_profile_registered() -> None:
    """The catalog resolves the family, its amendment, and 487."""
    assert get_family_profile("S-6") is PROFILE_FORM_S6
    assert get_family_profile("S-6/A") is PROFILE_FORM_S6
    assert get_family_profile("487") is PROFILE_FORM_S6


def test_alias_resolution() -> None:
    """487 is a listed spelling of the S-6 family; S-6EL24 is not."""
    assert resolve_alias("S-6") == "S-6"
    assert resolve_alias("S-6/A") == "S-6"
    assert resolve_alias("487") == "S-6"
    assert resolve_alias("S-6EL24") != "S-6"
    assert resolve_alias("S-6EL24/A") != "S-6"
