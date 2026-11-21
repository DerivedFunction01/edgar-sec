"""Tests for the shared registrant head-line scan."""

from __future__ import annotations

from edgar_sec.engine.forms.common.registrant_scan import (
    FACING_SHEET_SCAN,
    FORM_497_SCAN,
    ICA_HEAD_FALLBACK_SCAN,
    scan_registrant_name,
)


def test_named_configurations_pin_caller_gates() -> None:
    assert FACING_SHEET_SCAN.window == 80
    assert FACING_SHEET_SCAN.reject_dollar is True
    assert "washington" in FACING_SHEET_SCAN.skip_tokens
    assert "calculation of registration fee" in FACING_SHEET_SCAN.skip_tokens
    assert ICA_HEAD_FALLBACK_SCAN.window == 12
    assert ICA_HEAD_FALLBACK_SCAN.skip_tokens == ()
    assert ICA_HEAD_FALLBACK_SCAN.reject_dollar is False
    assert FORM_497_SCAN.window == 20
    assert FORM_497_SCAN.reject_dollar is True
    assert "prospectus" in FORM_497_SCAN.skip_tokens


def test_scan_returns_both_raw_and_normalized() -> None:
    hit = scan_registrant_name(["ACME $ TRUST INC"], ICA_HEAD_FALLBACK_SCAN)
    assert hit is not None
    assert hit.raw == "ACME $ TRUST INC"
    assert hit.name == "ACME $ TRUST"


def test_dollar_lines_rejected_only_when_configured() -> None:
    lines = ["ACME $ TRUST INC"]
    assert scan_registrant_name(lines, FACING_SHEET_SCAN) is None
    assert scan_registrant_name(lines, FORM_497_SCAN) is None
    assert scan_registrant_name(lines, ICA_HEAD_FALLBACK_SCAN) is not None


def test_skip_tokens_are_per_caller() -> None:
    lines = ["WASHINGTON TRUST COMPANY", "NEW FOUND GOLD CORP."]
    facing = scan_registrant_name(lines, FACING_SHEET_SCAN)
    assert facing is not None
    assert facing.name == "NEW FOUND GOLD CORP."
    fallback = scan_registrant_name(lines, ICA_HEAD_FALLBACK_SCAN)
    assert fallback is not None
    assert fallback.raw == "WASHINGTON TRUST COMPANY"

    lines = ["ACME PROSPECTUS TRUST INC", "UBS AG"]
    form_497 = scan_registrant_name(lines, FORM_497_SCAN)
    assert form_497 is not None
    assert form_497.raw == "UBS AG"
    facing = scan_registrant_name(lines, FACING_SHEET_SCAN)
    assert facing is not None
    assert facing.name == "ACME PROSPECTUS TRUST"


def test_windows_are_per_caller() -> None:
    def lines_with_name_at(index: int) -> list[str]:
        return ["filler"] * index + ["UBS AG"]

    assert scan_registrant_name(lines_with_name_at(11), ICA_HEAD_FALLBACK_SCAN)
    assert scan_registrant_name(lines_with_name_at(12), ICA_HEAD_FALLBACK_SCAN) is None
    assert scan_registrant_name(lines_with_name_at(12), FORM_497_SCAN)
    assert scan_registrant_name(lines_with_name_at(20), FORM_497_SCAN) is None
    assert scan_registrant_name(lines_with_name_at(20), FACING_SHEET_SCAN)
    assert scan_registrant_name(lines_with_name_at(80), FACING_SHEET_SCAN) is None


def test_unresolvable_heads_return_none() -> None:
    assert scan_registrant_name([], FACING_SHEET_SCAN) is None
    assert scan_registrant_name(["", "  ", "123"], FORM_497_SCAN) is None
