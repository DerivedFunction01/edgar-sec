"""Tests for Form 144 processing profile and catalog entry."""

from edgar_sec.domain.forms.common.aliases import resolve_alias
from edgar_sec.domain.forms.common.processing import AcquisitionOperation
from edgar_sec.domain.forms.families.form144.processing import PROFILE_FORM_144
from edgar_sec.domain.forms.families.processing_profiles import (
    get_family_entry,
    get_family_profile,
)


def test_form144_profile_properties():
    assert PROFILE_FORM_144.family == "144"
    assert PROFILE_FORM_144.preferred_operation == AcquisitionOperation.RENDER_TO_XML
    assert PROFILE_FORM_144.has_operation(AcquisitionOperation.RENDER_TO_XML)
    assert PROFILE_FORM_144.has_operation(AcquisitionOperation.RAW)


def test_form144_catalog_registration():
    entry = get_family_entry("144")
    assert entry is not None
    assert entry.family == "144"
    assert entry.profile == PROFILE_FORM_144

    profile = get_family_profile("144/A")
    assert profile is not None
    assert profile.family == "144"
    assert resolve_alias("144/A") == "144"
