from __future__ import annotations

from edgar_sec.domain.forms.families.form_sd.profiles import PRIMARY_PROFILE_SD


def test_primary_profile() -> None:
    assert PRIMARY_PROFILE_SD.family == "SD"
    assert PRIMARY_PROFILE_SD.designator_tokens == ("SD", "SD/A")
    assert PRIMARY_PROFILE_SD.commission_header_required is True
