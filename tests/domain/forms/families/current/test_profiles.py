from __future__ import annotations

from edgar_sec.domain.forms.families.current.profiles import (
    PRIMARY_PROFILE_6K,
    PRIMARY_PROFILE_8K,
)


def test_current_primary_profiles_split_by_form() -> None:
    assert PRIMARY_PROFILE_8K.family == "8-K"
    assert PRIMARY_PROFILE_6K.family == "6-K"
    assert PRIMARY_PROFILE_6K.designator_tokens == ("6-K", "6-K/A")
    assert PRIMARY_PROFILE_8K.designator_tokens != PRIMARY_PROFILE_6K.designator_tokens
