import pytest

from edgar_sec.domain.forms.families.beneficial_ownership.identifiers import (
    CUSIP_UNAVAILABLE_POLICY,
)


@pytest.mark.parametrize(
    "value",
    (
        "None",
        "None.",
        "NONE",
        " N/A ",
        "N/A.",
        "NA",
        "NA.",
        "NOT AVAILABLE",
        "Not   Applicable",
        "Not\tProvided",
        "UNKNOWN",
    ),
)
def test_known_cusip_unavailable_markers(value: str) -> None:
    assert CUSIP_UNAVAILABLE_POLICY.is_missing(value)


@pytest.mark.parametrize(
    "value",
    (
        "",
        "   ",
        "-",
        "--",
        "NULL",
        "UNKNOWN.",
        "NOT REPORTED",
        "N.A.",
        "N / A",
    ),
)
def test_unrecognized_cusip_markers_are_not_absence_proof(value: str) -> None:
    assert not CUSIP_UNAVAILABLE_POLICY.is_missing(value)
