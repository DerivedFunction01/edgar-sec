from __future__ import annotations

from edgar_sec.domain.forms.families.form_rega.profiles import (
    PRIMARY_PROFILE_1SA,
    PRIMARY_PROFILE_1U,
)


def test_primary_profiles_identify_report_faces() -> None:
    assert PRIMARY_PROFILE_1SA.family == "1-SA"
    assert PRIMARY_PROFILE_1SA.statutory_titles == (
        "semiannual report pursuant to regulation a",
    )
    assert PRIMARY_PROFILE_1SA.designator_tokens == ("1-SA", "1-SA/A")
    assert PRIMARY_PROFILE_1U.family == "1-U"
    assert PRIMARY_PROFILE_1U.statutory_titles == (
        "current report pursuant to regulation a",
    )
    assert PRIMARY_PROFILE_1U.designator_tokens == ("1-U", "1-U/A")
