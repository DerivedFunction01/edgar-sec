"""Tests for canonical cover vocabulary."""

from __future__ import annotations

from edgar_sec.domain.forms.common.vocabulary import (
    COVER_LABELS,
    FILER_ACCELERATED,
    FILER_EMERGING_GROWTH,
    FILER_LARGE_ACCELERATED,
    FILER_NON_ACCELERATED,
    FILER_SMALLER_REPORTING,
    FILER_TYPE_LABELS,
)


def test_filer_status_constants_are_the_canonical_stat_keys() -> None:
    """The solver's canonical_semantic_key maps labels onto exactly these."""
    assert FILER_LARGE_ACCELERATED == "large_accelerated_filer"
    assert FILER_ACCELERATED == "accelerated_filer"
    assert FILER_NON_ACCELERATED == "non_accelerated_filer"
    assert FILER_SMALLER_REPORTING == "smaller_reporting_company"
    assert FILER_EMERGING_GROWTH == "emerging_growth_company"


def test_filer_type_labels_map_keys_to_ordered_aliases() -> None:
    assert FILER_TYPE_LABELS == {
        FILER_LARGE_ACCELERATED: ("large accelerated filer",),
        FILER_ACCELERATED: ("accelerated filer",),
        FILER_NON_ACCELERATED: ("non-accelerated filer", "non accelerated filer"),
        FILER_SMALLER_REPORTING: ("smaller reporting company",),
        FILER_EMERGING_GROWTH: ("emerging growth company",),
    }


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
