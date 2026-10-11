"""Tests for Item 601 and Form 20-F coverage ledger."""

from __future__ import annotations

from edgar_sec.domain.forms.exhibits.coverage import (
    _LOOKUP,
    get_coverage_entry,
    is_code_reserved,
    is_code_supported,
    list_coverage_entries,
)


def test_601_coverage_entries_exist():
    """All Item 601 items 1-107 resolve to unique entries."""
    entries = list_coverage_entries("reg_s_k_item_601")
    assert len(entries) == 107
    codes = {e.code for e in entries}
    assert codes == {str(i) for i in range(1, 108)}


def test_601_candidate_items():
    """Candidate items have correct status."""
    candidate_items = (
        [1, 2, 5, 8, 9]
        + list(range(13, 20))
        + list(range(21, 26))
        + list(range(32, 37))
        + list(range(95, 99))
        + [107]
    )
    for item in candidate_items:
        entry = get_coverage_entry("reg_s_k_item_601", str(item))
        assert entry is not None
        assert entry.coverage_status == "candidate"


def test_601_partial_items():
    """Partial items have correct status."""
    partial_items = [3, 4, 10, 31, 99]
    for item in partial_items:
        entry = get_coverage_entry("reg_s_k_item_601", str(item))
        assert entry is not None
        assert entry.coverage_status == "partial"


def test_601_unsupported_items():
    """Unsupported items have correct status."""
    unsupported_items = [7, 20] + list(range(101, 105)) + [106]
    for item in unsupported_items:
        entry = get_coverage_entry("reg_s_k_item_601", str(item))
        assert entry is not None
        assert entry.coverage_status == "unsupported"


def test_601_reserved_items():
    """Reserved items have correct status."""
    reserved_items = (
        [6, 11, 12] + list(range(26, 31)) + list(range(37, 95)) + [100, 105]
    )
    for item in reserved_items:
        entry = get_coverage_entry("reg_s_k_item_601", str(item))
        assert entry is not None
        assert entry.coverage_status == "reserved"


def test_601_is_code_reserved():
    """is_code_reserved returns True for reserved codes."""
    assert is_code_reserved("reg_s_k_item_601", "6") is True
    assert is_code_reserved("reg_s_k_item_601", "1") is False


def test_601_is_code_supported():
    """is_code_supported returns True for candidate/partial/unsupported."""
    assert is_code_supported("reg_s_k_item_601", "1") is True
    assert is_code_supported("reg_s_k_item_601", "6") is False


def test_20f_coverage_entries_exist():
    """All Form 20-F items 1-104 resolve to entries."""
    entries = list_coverage_entries("form_20f")
    assert len(entries) == 104
    codes = {e.code for e in entries}
    assert codes == {str(i) for i in range(1, 105)}


def test_20f_all_disabled_or_reserved():
    """Form 20-F entries are disabled (1-84) or reserved (85-104)."""
    entries = list_coverage_entries("form_20f")
    for entry in entries:
        assert entry.coverage_status in ("disabled", "reserved")


def test_collision_resolution():
    """Different authorities have distinct entries for same code."""
    entry_601 = get_coverage_entry("reg_s_k_item_601", "1")
    entry_20f = get_coverage_entry("form_20f", "1")
    assert entry_601 is not None
    assert entry_20f is not None
    assert entry_601.authority_id != entry_20f.authority_id


def test_unknown_authority_returns_none():
    """Unknown authority returns None."""
    assert get_coverage_entry("unknown_auth", "1") is None


def test_unknown_code_returns_none():
    """Unknown code returns None."""
    assert get_coverage_entry("reg_s_k_item_601", "999") is None
