from __future__ import annotations

import pytest

from edgar_sec.domain.identity import (
    AccessionNumber,
    Cik,
    accession_year,
    is_hyphenated_accession,
)


def test_cik_creation_and_formatting() -> None:
    cik1 = Cik.from_raw("0000320193")
    assert cik1.value == 320193
    assert cik1.to_10digit() == "0000320193"
    assert str(cik1) == "0000320193"
    assert int(cik1) == 320193

    cik2 = Cik.from_raw(320193)
    assert cik1 == cik2

    cik_zero = Cik.from_raw("0000000000")
    assert cik_zero.value == 0
    assert cik_zero.to_10digit() == "0000000000"

    with pytest.raises(ValueError, match="invalid CIK value"):
        Cik(-1)

    with pytest.raises(ValueError, match="invalid CIK value"):
        Cik(10_000_000_000)


def test_accession_number_validation() -> None:
    acc = AccessionNumber("0000320193-23-000106")
    assert str(acc) == "0000320193-23-000106"
    assert acc.normalized == "000032019323000106"

    with pytest.raises(ValueError, match="invalid SEC accession number format"):
        AccessionNumber("invalid-accession")

    with pytest.raises(ValueError, match="invalid SEC accession number format"):
        AccessionNumber("000032019323000106")


def test_accession_year_uses_the_fixed_90_pivot() -> None:
    """Homed verbatim from form_tender: 90-99 are 19xx, 00-89 20xx."""
    assert accession_year("0000320193-95-000106") == 1995
    assert accession_year("0000320193-24-000106") == 2024
    assert accession_year("0000320193-89-000106") == 2089
    assert accession_year("not-an-accession") is None


def test_hyphenated_accession_predicate_is_exact() -> None:
    assert is_hyphenated_accession("0000320193-23-000106")
    assert not is_hyphenated_accession("x0000320193-23-000106")
    assert not is_hyphenated_accession("0000320193-23-000106-extra")
    assert not is_hyphenated_accession("0000320193-23-000106\n")
