"""Tests for ownership family processing profiles."""

from __future__ import annotations

from edgar_sec.domain.forms.common.processing import AcquisitionOperation
from edgar_sec.domain.forms.families.ownership.processing import PROFILE


def test_ownership_profile_allows_raw_and_render_to_xml() -> None:
    assert PROFILE.family == "4"
    assert PROFILE.version == "v1"
    assert PROFILE.allowed_operations == frozenset(
        {AcquisitionOperation.RAW, AcquisitionOperation.RENDER_TO_XML}
    )
    assert PROFILE.has_operation(AcquisitionOperation.RAW)
    assert PROFILE.has_operation(AcquisitionOperation.RENDER_TO_XML)
    assert not PROFILE.has_operation(AcquisitionOperation.RENDER_TO_TXT)
