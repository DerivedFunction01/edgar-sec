"""Unit and contract tests for edgar_sec.engine.document.signatures."""

from __future__ import annotations

from edgar_sec.engine.document.signatures import (
    find_signature_regions,
    heal_mangled_signature_text,
    is_conformed_signature_line,
    is_signature_label_line,
    normalize_signature_marker,
)


def test_is_conformed_signature_line() -> None:
    assert is_conformed_signature_line("/s/ John Doe")
    assert is_conformed_signature_line("  By: /s/ Jane Smith")
    assert not is_conformed_signature_line("Signed by John Doe")


def test_is_signature_label_line() -> None:
    assert is_signature_label_line("By: John Doe")
    assert is_signature_label_line("Name: Jane Smith")
    assert is_signature_label_line("Title: Chief Executive Officer")
    assert is_signature_label_line("Date: December 31, 2024")
    assert not is_signature_label_line("Note: see item 1")


def test_normalize_signature_marker() -> None:
    assert normalize_signature_marker("/s/John Doe") == "/s/ John Doe"
    assert normalize_signature_marker("/ S / John Doe") == "/s/ John Doe"
    assert normalize_signature_marker("Regular text") == "Regular text"


def test_heal_mangled_signature_text() -> None:
    # Letter-spaced signature
    mangled = "/s/ J O H N   D O E"
    healed = heal_mangled_signature_text(mangled)
    assert "JOHN" in healed


def test_find_signature_regions_with_dates() -> None:
    lines = [
        "SIGNATURES",
        "Pursuant to the requirements of the Securities Exchange Act of 1934...",
        "",
        "/s/ Jane Doe               Chief Executive Officer",
        "12/31/95                   Date",
        "",
        "/s/ John Smith             Chief Financial Officer",
        "December 31, 1995          Date",
    ]
    regions = find_signature_regions(lines)
    assert len(regions) > 0
    assert regions[0].signer_count >= 1
