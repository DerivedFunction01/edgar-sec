"""Tests for ownership family processing profiles."""

from __future__ import annotations

from edgar_sec.domain.forms.common.processing import AcquisitionOperation
from edgar_sec.domain.forms.families.ownership.processing import (
    PROFILE_FORM_3,
    PROFILE_FORM_4,
    PROFILE_FORM_5,
)


def test_ownership_profile_allows_raw_and_render_to_xml() -> None:
    assert PROFILE_FORM_4.family == "4"
    assert PROFILE_FORM_4.version == "v1"
    assert PROFILE_FORM_4.allowed_operations == frozenset(
        {AcquisitionOperation.RAW, AcquisitionOperation.RENDER_TO_XML}
    )
    assert PROFILE_FORM_4.has_operation(AcquisitionOperation.RAW)
    assert PROFILE_FORM_4.has_operation(AcquisitionOperation.RENDER_TO_XML)
    assert not PROFILE_FORM_4.has_operation(AcquisitionOperation.RENDER_TO_TXT)


def test_ownership_profiles_form_3_and_5() -> None:
    assert PROFILE_FORM_3.family == "3"
    assert PROFILE_FORM_3.has_operation(AcquisitionOperation.RAW)
    assert PROFILE_FORM_3.has_operation(AcquisitionOperation.RENDER_TO_XML)
    assert PROFILE_FORM_5.family == "5"
    assert PROFILE_FORM_5.has_operation(AcquisitionOperation.RAW)
    assert PROFILE_FORM_5.has_operation(AcquisitionOperation.RENDER_TO_XML)
