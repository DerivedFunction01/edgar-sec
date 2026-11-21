from __future__ import annotations

from edgar_sec.domain.forms.families.beneficial_ownership.processing import (
    PROFILE_SCHEDULE_13D,
    PROFILE_SCHEDULE_13G,
)
from edgar_sec.domain.forms.families.processing_profiles import get_family_entry


def test_schedule13d_profile_enables_raw_text_and_xml_operations() -> None:
    assert PROFILE_SCHEDULE_13D.family == "13D"
    assert (
        PROFILE_SCHEDULE_13D.review_analyzer
        == "edgar_sec.engine.forms.beneficial_ownership.analysis"
    )
    entry = get_family_entry("13D")
    assert entry is not None
    assert (
        entry.profile.review_analyzer
        == "edgar_sec.engine.forms.beneficial_ownership.analysis"
    )


def test_schedule13g_profile_enables_raw_text_and_xml_operations() -> None:
    assert PROFILE_SCHEDULE_13G.family == "13G"
    assert (
        PROFILE_SCHEDULE_13G.review_analyzer
        == "edgar_sec.engine.forms.beneficial_ownership.analysis"
    )
