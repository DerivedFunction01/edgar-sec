from __future__ import annotations

from edgar_sec.domain.forms.common.aliases import resolve_alias
from edgar_sec.domain.forms.families.form_tender.profiles import PRIMARY_PROFILE_TENDER


def test_tender_primary_profile() -> None:
    assert PRIMARY_PROFILE_TENDER.family == "SC TO"
    assert "schedule to" in PRIMARY_PROFILE_TENDER.statutory_titles
    assert "SC TO-T" in PRIMARY_PROFILE_TENDER.designator_tokens
    assert "SC 13E3" in PRIMARY_PROFILE_TENDER.designator_tokens


def test_tender_alias_resolution() -> None:
    for code in ("SC TO-T", "SC TO-I/A", "SC TO-C", "SC 14D9", "SC14D9F/A"):
        assert resolve_alias(code) == "SC TO"
    for code in ("SC 13E3", "SC 13E3/A", "SC 13E4", "SC 13E4/A"):
        assert resolve_alias(code) == "SC TO"
    for code in ("SC 14D1", "SC 14D1/A", "SC14D1F", "SC14D1F/A"):
        assert resolve_alias(code) == "SC TO"
