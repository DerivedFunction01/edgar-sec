from __future__ import annotations

from edgar_sec.domain.forms.exhibits.coverage import get_coverage_entry
from edgar_sec.domain.forms.exhibits.profiles import (
    ABS_EE_AUTHORITY_PROFILE,
    get_authorities_for_form,
    get_exhibit_authority_profile,
)


def test_reg_ab_authority_registered_for_both_hosts() -> None:
    assert get_exhibit_authority_profile("reg_ab") is ABS_EE_AUTHORITY_PROFILE
    assert ABS_EE_AUTHORITY_PROFILE in get_authorities_for_form("ABS-EE")
    assert ABS_EE_AUTHORITY_PROFILE in get_authorities_for_form("10-D")


def test_asset_data_codes_have_coverage_entries() -> None:
    ex102 = get_coverage_entry("reg_ab", "EX-102")
    ex103 = get_coverage_entry("reg_ab", "EX-103")
    assert ex102 is not None and ex102.code == "102"
    assert ex103 is not None and ex103.code == "103"
