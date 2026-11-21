"""Tests for the N-23C notice family processing profiles."""

from edgar_sec.domain.forms.common.aliases import resolve_alias
from edgar_sec.domain.forms.common.processing import AcquisitionOperation
from edgar_sec.domain.forms.families.form_n23c.processing import (
    PROFILE_FORM_N23C1,
    PROFILE_FORM_N23C2,
    PROFILE_FORM_N23C3,
)
from edgar_sec.domain.forms.families.form_n23c.reports import (
    FormN23C1Report,
    FormN23C2Report,
    FormN23C3Report,
)
from edgar_sec.domain.forms.families.processing_profiles import get_family_profile

_PROFILES = (
    (PROFILE_FORM_N23C1, "N-23C-1", FormN23C1Report),
    (PROFILE_FORM_N23C2, "N-23C-2", FormN23C2Report),
    (PROFILE_FORM_N23C3, "N-23C-3", FormN23C3Report),
)


def test_profile_operations() -> None:
    """Profiles allow RAW + RENDER_TO_TXT with text preferred."""
    for profile, family, report in _PROFILES:
        assert profile.family == family
        assert profile.allowed_operations == frozenset(
            {AcquisitionOperation.RAW, AcquisitionOperation.RENDER_TO_TXT}
        )
        assert profile.preferred_operation == AcquisitionOperation.RENDER_TO_TXT
        assert profile.report_class is report
        assert profile.review_analyzer is None
        assert profile.has_sections is True
        assert profile.has_xbrl is False


def test_profile_registered() -> None:
    """The catalog resolves each family and its strings to the profile."""
    assert get_family_profile("N-23C-1") is PROFILE_FORM_N23C1
    assert get_family_profile("N-23C-1/A") is PROFILE_FORM_N23C1
    assert get_family_profile("N-23C-2") is PROFILE_FORM_N23C2
    assert get_family_profile("N-23C-2/A") is PROFILE_FORM_N23C2
    for form in (
        "N-23C3A",
        "N-23C3A/A",
        "N-23C3B",
        "N-23C3B/A",
        "N-23C3C",
        "N-23C3C/A",
    ):
        assert get_family_profile(form) is PROFILE_FORM_N23C3


def test_all_ten_codes_resolve_to_their_family() -> None:
    """Every code in the line resolves through the production alias table."""
    expected = {
        "N-23C-1": "N-23C-1",
        "N-23C-1/A": "N-23C-1",
        "N-23C-2": "N-23C-2",
        "N-23C-2/A": "N-23C-2",
        "N-23C3A": "N-23C-3",
        "N-23C3A/A": "N-23C-3",
        "N-23C3B": "N-23C-3",
        "N-23C3B/A": "N-23C-3",
        "N-23C3C": "N-23C-3",
        "N-23C3C/A": "N-23C-3",
    }
    for form, family in expected.items():
        assert resolve_alias(form) == family
