"""Tests for the 40-24B2 processing profile."""

from edgar_sec.domain.forms.common.aliases import resolve_alias
from edgar_sec.domain.forms.common.processing import AcquisitionOperation
from edgar_sec.domain.forms.families.form_4024b2.processing import PROFILE_FORM_4024B2
from edgar_sec.domain.forms.families.processing_profiles import get_family_profile


def test_profile_operations() -> None:
    """Profile allows RAW + RENDER_TO_TXT with text preferred, nothing more."""
    assert PROFILE_FORM_4024B2.family == "40-24B2"
    assert PROFILE_FORM_4024B2.allowed_operations == frozenset(
        {AcquisitionOperation.RAW, AcquisitionOperation.RENDER_TO_TXT}
    )
    assert PROFILE_FORM_4024B2.preferred_operation == AcquisitionOperation.RENDER_TO_TXT
    assert PROFILE_FORM_4024B2.has_operation(AcquisitionOperation.RAW)
    assert not PROFILE_FORM_4024B2.has_operation(AcquisitionOperation.RENDER_TO_XML)
    assert PROFILE_FORM_4024B2.report_class is None
    assert PROFILE_FORM_4024B2.review_analyzer is None
    assert PROFILE_FORM_4024B2.has_sections is False
    assert PROFILE_FORM_4024B2.has_toc is False
    assert PROFILE_FORM_4024B2.has_notes is False
    assert PROFILE_FORM_4024B2.has_xbrl is False


def test_profile_registered() -> None:
    """The catalog resolves the family and its amendment to the profile."""
    assert get_family_profile("40-24B2") is PROFILE_FORM_4024B2
    assert get_family_profile("40-24B2/A") is PROFILE_FORM_4024B2


def test_alias_resolution() -> None:
    """The amendment spelling resolves to the canonical family."""
    assert resolve_alias("40-24B2") == "40-24B2"
    assert resolve_alias("40-24B2/A") == "40-24B2"
