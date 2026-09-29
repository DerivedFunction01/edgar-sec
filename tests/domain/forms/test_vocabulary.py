"""Unit tests for domain.forms.vocabulary.

The state-vocabulary helper is derived from ``domain.taxonomy.jurisdictions``,
which is the canonical source. It was previously restated here and silently
omitted Guam, Puerto Rico and the Virgin Islands, so a cover page that said
"PUERTO RICO" was not recognised as a state value. These tests pin the
derivation so a restatement cannot drift again, and pin the grouped
vocabulary constants the checkmark solver keys off.
"""

from __future__ import annotations

import pytest

from edgar_sec.domain.forms.vocabulary import (
    _US_STATES,
    CHECKBOX_GRID_RE,
    COVER_LABELS,
    FILER_ACCELERATED,
    FILER_EMERGING_GROWTH,
    FILER_LARGE_ACCELERATED,
    FILER_NON_ACCELERATED,
    FILER_SMALLER_REPORTING,
    REPORT_ANNUAL,
    REPORT_QUARTERLY,
    is_state_value,
)
from edgar_sec.domain.taxonomy.jurisdictions import (
    STATE_NAMES,
    STATE_POSTAL_CODES,
)


def test_state_vocabulary_is_derived_from_the_canonical_jurisdiction_list() -> None:
    """The two layers share one list; a restatement here would drift again."""
    assert _US_STATES == frozenset(
        [*STATE_POSTAL_CODES, *(name.upper() for name in STATE_NAMES)]
    )


def test_territories_are_recognized_state_values() -> None:
    """The omission that motivated the derivation."""
    for value in ("PUERTO RICO", "PR", "VIRGIN ISLANDS", "VI", "GUAM", "GU"):
        assert is_state_value(value), value


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("CA", True),
        ("ca", True),
        ("  NY  ", True),
        ("District of Columbia", True),
        ("XX", False),
        ("CANADA", False),
        ("", False),
        ("    ", False),
        ("Not a state", False),
    ],
)
def test_is_state_value(value: str, expected: bool) -> None:
    assert is_state_value(value) == expected


def test_filer_status_constants_are_the_canonical_stat_keys() -> None:
    """The solver's canonical_semantic_key maps labels onto exactly these."""
    assert FILER_LARGE_ACCELERATED == "large_accelerated_filer"
    assert FILER_ACCELERATED == "accelerated_filer"
    assert FILER_NON_ACCELERATED == "non_accelerated_filer"
    assert FILER_SMALLER_REPORTING == "smaller_reporting_company"
    assert FILER_EMERGING_GROWTH == "emerging_growth_company"


def test_report_period_constants_are_the_canonical_stat_keys() -> None:
    assert REPORT_ANNUAL == "annual"
    assert REPORT_QUARTERLY == "quarterly"


def test_cover_labels_are_grouped_and_nonempty() -> None:
    assert set(COVER_LABELS) == {
        "commission_file_number",
        "irs_ein",
        "principal_address",
        "registrant_name",
        "securities_12b",
        "state_of_incorporation",
        "telephone",
        "zip_code",
    }
    for label, terms in COVER_LABELS.items():
        assert terms, f"cover label group {label} is empty"


def test_checkbox_grid_re_matches_a_marked_grid_row() -> None:
    assert CHECKBOX_GRID_RE.search("[ ] YES  [x] NO")


def test_identification_patterns_match_real_cover_values() -> None:
    """IRS_EIN_RE is the *label* pattern; EIN_VALUE_RE matches the digits."""
    from edgar_sec.domain.forms.vocabulary import EIN_VALUE_RE

    assert EIN_VALUE_RE.search("00-0000000")
