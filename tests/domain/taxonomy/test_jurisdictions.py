from __future__ import annotations

from types import MappingProxyType

import pytest

from edgar_sec.domain.taxonomy.jurisdictions import (
    EDGAR_JURISDICTION_CODES,
    EDGAR_JURISDICTION_CODES_BY_NAME,
    EDGAR_JURISDICTION_NAMES,
    STATE_POSTAL_CODES,
    edgar_jurisdiction_code,
    edgar_jurisdiction_code_in_text,
)


def test_edgar_jurisdiction_vocabulary_is_complete_and_immutable() -> None:
    assert len(EDGAR_JURISDICTION_CODES) == 332
    assert EDGAR_JURISDICTION_CODES == frozenset(EDGAR_JURISDICTION_NAMES)
    assert STATE_POSTAL_CODES <= EDGAR_JURISDICTION_CODES
    assert EDGAR_JURISDICTION_NAMES["X1"] == "UNITED STATES"
    assert EDGAR_JURISDICTION_NAMES["A0"] == "ALBERTA, CANADA"
    assert EDGAR_JURISDICTION_NAMES["XX"] == "Unknown"
    assert isinstance(EDGAR_JURISDICTION_NAMES, MappingProxyType)
    assert isinstance(EDGAR_JURISDICTION_CODES_BY_NAME, MappingProxyType)
    with pytest.raises(TypeError):
        EDGAR_JURISDICTION_NAMES["ZZ"] = "UNKNOWN"  # type: ignore[index]


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("Arizona", "AZ"),
        ("UNITED STATES", "X1"),
        ("A0", "A0"),
        ("Arizona corporation", None),
        ("ZZ", None),
    ],
)
def test_edgar_jurisdiction_name_normalization(
    source: str, expected: str | None
) -> None:
    assert edgar_jurisdiction_code(source) == expected


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("A Delaware Limited Liability Company", "DE"),
        ("State of New York", "NY"),
        ("State of New Jersey", "NJ"),
        ("Commonwealth of Pennsylvania", "PA"),
        ("British Virgin Islands", "D8"),
        ("United States of America", "X1"),
        ("USA", "X1"),
        ("U.S.A.", "X1"),
        ("México", "O5"),
        ("Canadian", "Z4"),
        ("British", "X0"),
        ("Norwegian", "Q8"),
        ("Panamanian", "R1"),
        ("Swiss", "V7"),
        ("Scotland", "X0"),
        ("Alberta", "A0"),
        ("Ontario", "A6"),
        ("State of Delaware, United States of America", "DE"),
        ("U.S. Citizen", "X1"),
        ("A Canadian Citizen", "Z4"),
        ("Sydney, New South Wales Australia", "C3"),
        ("Anguilla, British West Indies", "1A"),
        ("225 South Lake Ave., #400, Pasadena, CA 91101", "CA"),
        ("Spokane, WA", "WA"),
        (
            "Northern Trust Corporation- a Delaware corporation with principal offices in Chicago, Illinois",
            "DE",
        ),
        ("A DELWARE CORPORATION SADDLE BROOK, NJ 07663", "DE"),
        ("United Kingdom & United States", None),
    ],
)
def test_edgar_jurisdiction_code_in_text(source: str, expected: str | None) -> None:
    assert edgar_jurisdiction_code_in_text(source) == expected
