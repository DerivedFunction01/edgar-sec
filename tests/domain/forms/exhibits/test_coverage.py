"""Tests for Item 601 and Form 20-F coverage ledger."""

from __future__ import annotations

from edgar_sec.domain.forms.exhibits.coverage import (
    _LOOKUP,
    get_coverage_entry,
    is_code_historical,
    is_code_reserved,
    is_code_supported,
    list_coverage_entries,
)


def test_601_coverage_entries_exist():
    """All Item 601 items resolve to entries."""
    entries = list_coverage_entries("reg_s_k_item_601")
    assert len(entries) > 0
    codes = {e.code for e in entries}
    assert "1" in codes
    assert "3" in codes
    assert "10" in codes
    assert "21" in codes
    assert "31" in codes
    assert "32" in codes
    assert "99" in codes
    assert "101" in codes
    assert "107" in codes


def test_601_authentic_titles():
    """Item 601 titles are authentic (not Form 10-K Part/Item names)."""
    entry = get_coverage_entry("reg_s_k_item_601", "1")
    assert entry is not None
    assert entry.title == "Underwriting agreement"

    entry = get_coverage_entry("reg_s_k_item_601", "3")
    assert entry is not None
    assert entry.title == "Articles of incorporation and bylaws"

    entry = get_coverage_entry("reg_s_k_item_601", "4")
    assert entry is not None
    assert (
        entry.title
        == "Instruments defining the rights of security holders, including indentures"
    )

    entry = get_coverage_entry("reg_s_k_item_601", "10")
    assert entry is not None
    assert entry.title == "Material contracts"

    entry = get_coverage_entry("reg_s_k_item_601", "21")
    assert entry is not None
    assert entry.title == "Subsidiaries of the registrant"

    entry = get_coverage_entry("reg_s_k_item_601", "31")
    assert entry is not None
    assert "Rule 13a-14(a)/15d-14(a) Certifications" in entry.title

    entry = get_coverage_entry("reg_s_k_item_601", "32")
    assert entry is not None
    assert "Section 1350 Certifications" in entry.title


def test_601_historical_exhibits():
    """Historical exhibits have correct titles and status."""
    entry = get_coverage_entry("reg_s_k_item_601", "11")
    assert entry is not None
    assert entry.title == "Statement re computation of per share earnings"
    assert entry.coverage_status == "historical"
    assert is_code_historical("reg_s_k_item_601", "11") is True

    entry = get_coverage_entry("reg_s_k_item_601", "27")
    assert entry is not None
    assert entry.title == "Financial Data Schedule"
    assert entry.coverage_status == "historical"
    assert is_code_historical("reg_s_k_item_601", "27") is True

    entry = get_coverage_entry("reg_s_k_item_601", "26")
    assert entry is not None
    assert entry.coverage_status == "historical"

    entry = get_coverage_entry("reg_s_k_item_601", "100")
    assert entry is not None
    assert entry.title == "XBRL Related Documents"
    assert entry.coverage_status == "historical"


def test_601_historical_not_reserved():
    """Historical exhibits are NOT reserved."""
    assert is_code_reserved("reg_s_k_item_601", "11") is False
    assert is_code_reserved("reg_s_k_item_601", "27") is False
    assert is_code_historical("reg_s_k_item_601", "11") is True
    assert is_code_historical("reg_s_k_item_601", "27") is True


def test_601_subcode_lookup():
    """Sub-code lookups work correctly."""
    entry = get_coverage_entry("reg_s_k_item_601", "3.1")
    assert entry is not None
    assert "Articles" in entry.title

    entry = get_coverage_entry("reg_s_k_item_601", "31.1")
    assert entry is not None
    assert "CEO/CFO" in entry.title

    entry = get_coverage_entry("reg_s_k_item_601", "32.1")
    assert entry is not None
    assert "Section 906" in entry.title


def test_601_alias_lookup():
    """EX- prefix aliases are normalized."""
    entry = get_coverage_entry("reg_s_k_item_601", "EX-10")
    assert entry is not None
    assert entry.title == "Material contracts"

    entry = get_coverage_entry("reg_s_k_item_601", "EX-31.1")
    assert entry is not None


def test_20f_coverage_entries_exist():
    """All Form 20-F entries resolve."""
    entries = list_coverage_entries("form_20f")
    assert len(entries) > 0
    codes = {e.code for e in entries}
    assert "1" in codes
    assert "4" in codes
    assert "12" in codes
    assert "13" in codes
    assert "104" in codes


def test_20f_titles():
    """Form 20-F titles match Item 19 instructions."""
    entry = get_coverage_entry("form_20f", "1")
    assert entry is not None
    assert "articles of incorporation" in entry.title.lower()

    entry = get_coverage_entry("form_20f", "4")
    assert entry is not None
    assert entry.title == "Material contracts"

    entry = get_coverage_entry("form_20f", "12")
    assert entry is not None
    assert "Section 302" in entry.title

    entry = get_coverage_entry("form_20f", "13")
    assert entry is not None
    assert "Section 906" in entry.title


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
