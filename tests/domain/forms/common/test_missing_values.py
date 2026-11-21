import pytest

from edgar_sec.domain.forms.common.missing_values import (
    COMMON_NUMERIC_NULL_POLICY,
    MissingValuePolicy,
    classify_missing_value_token,
    normalize_missing_value_token,
)


@pytest.mark.parametrize(
    ("value", "normalized", "classified"),
    (
        ("  Not\tAvailable  ", "not available", "not available"),
        ("N/A", "n/a", "n/a"),
        ("N.A.", "n.a.", "n.a."),
        ("N / A", "n / a", "n / a"),
        ("", "", ""),
        (None, None, None),
    ),
)
def test_marker_normalization_and_classification(
    value: str | None, normalized: str | None, classified: str | None
) -> None:
    assert normalize_missing_value_token(value) == normalized
    assert classify_missing_value_token(value) == classified


def test_classification_does_not_make_every_marker_globally_missing() -> None:
    cusip_policy = MissingValuePolicy(frozenset({"unknown"}))

    assert classify_missing_value_token("UNKNOWN") == "unknown"
    assert not COMMON_NUMERIC_NULL_POLICY.is_missing("UNKNOWN")
    assert cusip_policy.is_missing("UNKNOWN")


@pytest.mark.parametrize("value", ("", " ", "-", "--", "none", "n/a", "nil", "null"))
def test_common_numeric_null_policy(value: str) -> None:
    assert COMMON_NUMERIC_NULL_POLICY.is_missing(value)


@pytest.mark.parametrize(
    "value",
    (
        "none.",
        "n/a.",
        "na",
        "unknown",
        "UNKNOWN.",
        "N.A.",
        "N / A",
        "NOT REPORTED",
    ),
)
def test_common_numeric_policy_rejects_other_classified_markers(value: str) -> None:
    assert classify_missing_value_token(value) is not None
    assert not COMMON_NUMERIC_NULL_POLICY.is_missing(value)
