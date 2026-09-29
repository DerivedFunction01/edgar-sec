"""Unit tests for edgar_sec.engine.forms.checkmarks.solver's pure core.

``canonical_semantic_key`` maps the free-form cover labels the SEC actually
prints onto the solver's canonical stat keys, without inventing a mapping for a
label it does not recognise — an unknown label must survive verbatim so the
caller can record it as unmatched rather than silently mis-filing it. The
family-to-schema mapping is pinned alongside it because 20-F used to be keyed
to the wrong family in the plugin registry.
"""

from __future__ import annotations

import pytest

from edgar_sec.domain.forms.schemas import (
    ANNUAL_CHECKBOX_SCHEMA,
    QUARTERLY_CHECKBOX_SCHEMA,
)
from edgar_sec.domain.forms.vocabulary import (
    FILER_ACCELERATED,
    FILER_EMERGING_GROWTH,
    FILER_LARGE_ACCELERATED,
    FILER_NON_ACCELERATED,
    FILER_SMALLER_REPORTING,
)
from edgar_sec.engine.forms.checkmarks.solver import (
    _schema_for_family as schema_for_family,
)
from edgar_sec.engine.forms.checkmarks.solver import canonical_semantic_key


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("Large accelerated filer", FILER_LARGE_ACCELERATED),
        ("LARGE ACCELERATED FILER", FILER_LARGE_ACCELERATED),
        ("large_accelerated_filer", FILER_LARGE_ACCELERATED),
        ("Non-accelerated filer", FILER_NON_ACCELERATED),
        ("Non accelerated filer", FILER_NON_ACCELERATED),
        ("Smaller reporting company", FILER_SMALLER_REPORTING),
        ("Emerging growth company", FILER_EMERGING_GROWTH),
        ("Accelerated filer", FILER_ACCELERATED),
    ],
)
def test_filer_labels_canonicalize(label: str, expected: str) -> None:
    assert canonical_semantic_key(label) == expected


def test_unknown_label_survives_verbatim() -> None:
    """No mapping for an unknown label: it must not silently become another key."""
    assert canonical_semantic_key("wattle and daub filer") == "wattle and daub filer"


def test_casing_and_punctuation_are_normalised_before_lookup() -> None:
    assert canonical_semantic_key("SMALLER   REPORTING COMPANY") == (
        FILER_SMALLER_REPORTING
    )


@pytest.mark.parametrize("family", ["10-K", "20-F", "10-k", "20-f"])
def test_annual_forms_use_the_annual_schema(family: str) -> None:
    assert schema_for_family(family) is ANNUAL_CHECKBOX_SCHEMA


def test_quarterly_form_uses_the_quarterly_schema() -> None:
    assert schema_for_family("10-Q") is QUARTERLY_CHECKBOX_SCHEMA


@pytest.mark.parametrize("family", [None, "8-K", "S-4", ""])
def test_unmodeled_families_have_no_cover_schema(family: str | None) -> None:
    assert schema_for_family(family) is None
