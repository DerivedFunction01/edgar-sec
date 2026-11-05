"""Tests for the canonical form-family alias registry."""

from __future__ import annotations

import pytest

from edgar_sec.domain.forms.common.aliases import (
    FORM_FAMILY_ALIASES,
    aliases_for_family,
    form_family,
    resolve_alias,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("10-K", "10-K"),
        ("10-K/A", "10-K"),
        ("10-K405", "10-K"),
        ("10-KSB", "10-K"),
        ("10KSB", "10-K"),
        ("10-KT", "10-K"),
        ("10-K/A-POS", "10-K"),
        ("10-Q", "10-Q"),
        ("10-QSB", "10-Q"),
        ("10-QT", "10-Q"),
        ("8-K", "8-K"),
        ("8-K12B", "8-K"),
        ("8-K12G3", "8-K"),
        ("8-K15D5", "8-K"),
        ("20-F", "20-F"),
        ("20FR12B", "20-F"),
        ("6-K", "6-K"),
        ("144", "144"),
        ("144/A", "144"),
        ("D", "D"),
        ("D/A", "D"),
        ("REGDEX", "D"),
        ("REGDEX/A", "D"),
        ("13F-HR", "13F"),
        ("13F-NT/A", "13F"),
        ("13FCONP", "13F"),
        ("SC 13D", "13D"),
        ("SCHEDULE 13D", "13D"),
        ("SC 13D/A", "13D"),
        ("SC 13G", "13G"),
        ("SCHEDULE 13G", "13G"),
        ("SC 13G/A", "13G"),
        ("S-3", "S-3"),
        ("S-3/A", "S-3"),
        ("S-3ASR", "S-3"),
        ("S-4", "S-4"),
        ("S-4/A", "S-4"),
        ("S-8", "S-8"),
        ("S-8/A", "S-8"),
        ("DEF 14A", "14A"),
        ("PRE 14A", "14A"),
        ("DEFA14A", "14A"),
        ("NT 10-K", "12B-25"),
        ("NT 10-Q", "12B-25"),
        ("NT 20-F", "12B-25"),
        ("NT 10-D", "12B-25"),
        ("NT 10-D/A", "12B-25"),
        ("NT 15D2", "12B-25"),
        ("NT 15D2/A", "12B-25"),
        ("15-12B", "15"),
        ("15-12G", "15"),
        ("15-15D", "15"),
        ("424B2", "424B"),
        ("424B5", "424B"),
        ("424A", "424B"),
        ("FWP", "FWP"),
        ("425", "425"),
        ("NPORT-P", "N-PORT"),
        ("NPORT-P/A", "N-PORT"),
        ("NPORT-EX", "N-PORT"),
        ("N-CEN", "N-CEN"),
        ("N-CEN/A", "N-CEN"),
        ("N-PX", "N-PX"),
        ("N-PX CTR", "N-PX"),
        ("N-MFP", "N-MFP"),
        ("N-CSR", "N-CSR"),
        ("N-CSRS/A", "N-CSR"),
        ("N-Q", "N-Q"),
        ("NSAR-A", "NSAR"),
        ("NSAR-B/A", "NSAR"),
        ("NSAR-U", "NSAR"),
        ("497", "497"),
        ("497K", "497"),
        ("497J", "497"),
        ("485BPOS", "485"),
        ("486APOS", "485"),
        ("N-14", "N-14"),
        ("N-14 8C", "N-14"),
        ("N-2", "N-2"),
        ("N-2ASR", "N-2"),
        ("F-1", "F-1"),
        ("F-1/A", "F-1"),
        ("F-3ASR", "F-3"),
        ("F-4", "F-4"),
        ("F-6EF", "F-6"),
        ("F-6 POS", "F-6"),
        ("F-9", "F-9"),
        ("F-10/A", "F-10"),
        ("F-80", "F-80"),
        ("F-N", "F-N"),
        ("40-F", "40-F"),
        ("40-F/A", "40-F"),
        ("SUPPL", "SUPPL"),
        ("SC TO-T", "SC TO"),
        ("SC TO-I/A", "SC TO"),
        ("SC TO-C", "SC TO"),
        ("SC 14D9", "SC TO"),
        ("SC 14D1/A", "SC TO"),
        ("DRS", "DRS"),
        ("DRS/A", "DRS"),
        ("DRSLTR", "DRS"),
        ("25", "25"),
        ("25-NSE", "25-NSE"),
        ("25-NSE/A", "25-NSE"),
        ("8-A12B", "8-A"),
        ("8-A12G/A", "8-A"),
        ("8-B12B", "8-B"),
        ("1-A", "1-A"),
        ("253G2", "1-A"),
        ("1-K", "1-K"),
        ("1-K/A", "1-K"),
        ("1-Z", "1-Z"),
        ("1-Z/A", "1-Z"),
        ("1-SA", "1-SA"),
        ("1-SA/A", "1-SA"),
        ("1-U", "1-U"),
        ("1-U/A", "1-U"),
        ("SD", "SD"),
        ("ARS", "ARS"),
        ("ABS-15G/A", "ABS"),
        ("10-D", "ABS"),
        ("18-K", "18-K"),
        ("ATS-N", "ATS-N"),
        ("ATS-N/CA", "ATS-N"),
        ("ATS-N/MA", "ATS-N"),
        ("ATS-N/OFA", "ATS-N"),
        ("ATS-N/UA", "ATS-N"),
        ("ATS-N-W", "ATS-N"),
        ("MA-I", "MA-I"),
        ("MA-I/A", "MA-I"),
        ("N-CR", "N-CR"),
        ("N-CR/A", "N-CR"),
        ("C", "C"),
        ("C/A", "C"),
        ("C-AR", "C"),
        ("C-AR-W", "C"),
    ],
)
def test_resolve_alias(raw: str, expected: str) -> None:
    assert resolve_alias(raw) == expected


def test_suffix_stripping_prefers_pos_before_amendment() -> None:
    assert form_family("10-K/A-POS") == "10-K"
    assert form_family("10-K/A_W") == "10-K"
    assert form_family("10-KMEF") == "10-K"


def test_all_suffixes_collapse_to_original() -> None:
    assert form_family("/A") == "/A"


def test_unknown_form_returns_none() -> None:
    assert resolve_alias("Not a Form") is None
    assert resolve_alias(None) is None
    assert resolve_alias("") is None


def test_aliases_for_family() -> None:
    assert "10-K405" in aliases_for_family("10-K")
    assert aliases_for_family("nope") == ()


def test_every_alias_resolves_to_its_own_family() -> None:
    for family, aliases in FORM_FAMILY_ALIASES.items():
        for alias in aliases:
            assert resolve_alias(alias) == family


@pytest.mark.parametrize(
    "raw",
    [
        # Correspondence / SEC actions: unruled (plan II R2), never aliased.
        "CORRESP",
        "UPLOAD",
        "EFFECT",
        "CT ORDER",
        "NO ACT",
        "IRANNOTICE",
        "CERT",
        # Disposition-only family (plan II Step 14 records, no alias).
        "F-X",
    ],
)
def test_unruled_and_disposition_only_codes_stay_unresolved(raw: str) -> None:
    assert resolve_alias(raw) is None
