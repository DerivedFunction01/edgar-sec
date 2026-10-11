from __future__ import annotations

import pytest

from edgar_sec.domain.forms.common.schemas import CoverCheckboxSchema
from edgar_sec.domain.forms.families.annual.checkmarks import ANNUAL_CHECKBOX_SCHEMA
from edgar_sec.domain.forms.families.current.checkmarks import (
    EIGHT_K_CHECKBOX_SCHEMA,
    SIX_K_CHECKBOX_SCHEMA,
)
from edgar_sec.domain.forms.families.processing_profiles import (
    get_family_entry,
    get_family_profile,
)
from edgar_sec.domain.forms.families.quarterly.checkmarks import (
    QUARTERLY_CHECKBOX_SCHEMA,
)


@pytest.mark.parametrize(
    ("family", "schema", "companion", "transition"),
    [
        ("10-K", ANNUAL_CHECKBOX_SCHEMA, "annual", "transition"),
        ("20-F", ANNUAL_CHECKBOX_SCHEMA, "annual", "transition"),
        ("10-Q", QUARTERLY_CHECKBOX_SCHEMA, "quarterly", "transition"),
        ("8-K", EIGHT_K_CHECKBOX_SCHEMA, None, None),
        ("6-K", SIX_K_CHECKBOX_SCHEMA, None, None),
    ],
)
def test_family_entry_owns_cover_selection(
    family: str,
    schema: CoverCheckboxSchema,
    companion: str | None,
    transition: str | None,
) -> None:
    entry = get_family_entry(family)

    assert entry is not None
    assert entry.cover_checkbox_schema is schema
    assert schema.report_period_companion == companion
    assert schema.report_period_transition == transition


def test_family_entry_lookup_resolves_form_aliases() -> None:
    assert get_family_entry("10-K/A") is get_family_entry("10-K")
    assert get_family_profile("10-K/A") is get_family_profile("10-K")


def test_unknown_family_has_no_catalog_entry() -> None:
    assert get_family_entry("S-1") is None
    assert get_family_profile("S-1") is None


def test_current_forms_have_no_period_label_schema() -> None:
    assert EIGHT_K_CHECKBOX_SCHEMA.report_period_companion is None
    assert EIGHT_K_CHECKBOX_SCHEMA.report_period_transition is None
    assert SIX_K_CHECKBOX_SCHEMA.report_period_companion is None
    assert SIX_K_CHECKBOX_SCHEMA.report_period_transition is None
