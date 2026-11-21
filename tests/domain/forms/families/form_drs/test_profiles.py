from __future__ import annotations

from edgar_sec.domain.forms.common.aliases import resolve_alias
from edgar_sec.domain.forms.families.form_drs.profiles import PRIMARY_PROFILE_DRS


def test_drs_primary_profile() -> None:
    assert PRIMARY_PROFILE_DRS.family == "DRS"
    assert "as confidentially submitted" in PRIMARY_PROFILE_DRS.statutory_titles
    assert "DRSLTR" in PRIMARY_PROFILE_DRS.designator_tokens
    assert PRIMARY_PROFILE_DRS.commission_header_required is False


def test_drs_alias_resolution() -> None:
    for code in ("DRS", "DRS/A", "DRSLTR"):
        assert resolve_alias(code) == "DRS"
