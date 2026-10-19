from __future__ import annotations

from types import MappingProxyType

import pytest

from edgar_sec.domain.taxonomy.jurisdictions import (
    EDGAR_JURISDICTION_CODES,
    EDGAR_JURISDICTION_CODES_BY_NAME,
    EDGAR_JURISDICTION_NAMES,
    STATE_POSTAL_CODES,
    edgar_jurisdiction_code,
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
