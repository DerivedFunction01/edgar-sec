from __future__ import annotations

import pytest

from edgar_sec.domain.forms.common.schemas import CoverCheckboxSchema
from edgar_sec.domain.forms.families.annual.checkmarks import ANNUAL_CHECKBOX_SCHEMA
from edgar_sec.domain.forms.families.current.checkmarks import (
    EIGHT_K_CHECKBOX_SCHEMA,
    SIX_K_CHECKBOX_SCHEMA,
)
from edgar_sec.domain.forms.families.form_12b25.checkmarks import (
    FORM_12B25_CHECKBOX_SCHEMA,
)
from edgar_sec.domain.forms.families.form_12b25.processing import (
    PROFILE_FORM_12B25,
)
from edgar_sec.domain.forms.families.form_12b25.taxonomy import FORM_12B25_ITEMS
from edgar_sec.domain.forms.families.form_15.checkmarks import (
    FORM_15_CHECKBOX_SCHEMA,
)
from edgar_sec.domain.forms.families.form_11k.checkmarks import (
    FORM_11K_CHECKBOX_SCHEMA,
)
from edgar_sec.domain.forms.families.form_11k.processing import PROFILE_FORM_11K
from edgar_sec.domain.forms.families.form_11k.taxonomy import FORM_11K_ITEMS
from edgar_sec.domain.forms.families.form_14a.checkmarks import (
    FORM_14A_CHECKBOX_SCHEMA,
)
from edgar_sec.domain.forms.families.form_14a.processing import PROFILE_FORM_14A
from edgar_sec.domain.forms.families.form_14a.taxonomy import FORM_14A_ITEMS
from edgar_sec.domain.forms.families.form_15.processing import PROFILE_FORM_15
from edgar_sec.domain.forms.families.form_424b.processing import PROFILE_FORM_424B
from edgar_sec.domain.forms.families.form_424b.taxonomy import FORM_424B_ITEMS
from edgar_sec.domain.forms.families.form_f1.checkmarks import (
    FORM_F1_CHECKBOX_SCHEMA,
    FORM_F2_CHECKBOX_SCHEMA,
)
from edgar_sec.domain.forms.families.form_f1.processing import (
    PROFILE_FORM_F1,
    PROFILE_FORM_F2,
)
from edgar_sec.domain.forms.families.form_f1.taxonomy import (
    FORM_F1_ITEMS,
    FORM_F2_ITEMS,
)
from edgar_sec.domain.forms.families.form_f3.checkmarks import (
    FORM_F3_CHECKBOX_SCHEMA,
)
from edgar_sec.domain.forms.families.form_f3.processing import PROFILE_FORM_F3
from edgar_sec.domain.forms.families.form_f3.taxonomy import FORM_F3_ITEMS
from edgar_sec.domain.forms.families.form_f4.checkmarks import (
    FORM_F4_CHECKBOX_SCHEMA,
)
from edgar_sec.domain.forms.families.form_f4.processing import PROFILE_FORM_F4
from edgar_sec.domain.forms.families.form_f4.taxonomy import FORM_F4_ITEMS
from edgar_sec.domain.forms.families.form_40f.checkmarks import (
    FORM_40F_CHECKBOX_SCHEMA,
)
from edgar_sec.domain.forms.families.form_40f.processing import PROFILE_FORM_40F
from edgar_sec.domain.forms.families.form_f6.checkmarks import (
    FORM_F6_CHECKBOX_SCHEMA,
)
from edgar_sec.domain.forms.families.form_f6.processing import PROFILE_FORM_F6
from edgar_sec.domain.forms.families.form_f6.taxonomy import FORM_F6_ITEMS
from edgar_sec.domain.forms.families.form_fn.checkmarks import (
    FORM_FN_CHECKBOX_SCHEMA,
)
from edgar_sec.domain.forms.families.form_fn.processing import PROFILE_FORM_FN
from edgar_sec.domain.forms.families.form_mjds.checkmarks import (
    FORM_F7_CHECKBOX_SCHEMA,
    FORM_F8_CHECKBOX_SCHEMA,
    FORM_F9_CHECKBOX_SCHEMA,
    FORM_F10_CHECKBOX_SCHEMA,
    FORM_F80_CHECKBOX_SCHEMA,
)
from edgar_sec.domain.forms.families.form_mjds.processing import (
    PROFILE_FORM_F7,
    PROFILE_FORM_F8,
    PROFILE_FORM_F9,
    PROFILE_FORM_F10,
    PROFILE_FORM_F80,
)
from edgar_sec.domain.forms.families.form_mjds.taxonomy import (
    FORM_F7_ITEMS,
    FORM_F8_ITEMS,
    FORM_F9_ITEMS,
    FORM_F10_ITEMS,
    FORM_F80_ITEMS,
)
from edgar_sec.domain.forms.families.form_suppl.processing import PROFILE_FORM_SUPPL
from edgar_sec.domain.forms.families.form_425.processing import PROFILE_FORM_425
from edgar_sec.domain.forms.families.form_fwp.processing import PROFILE_FORM_FWP
from edgar_sec.domain.forms.families.form_fwp.taxonomy import FORM_FWP_ITEMS
from edgar_sec.domain.forms.families.processing_profiles import (
    get_lazy_index_trigger,
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
    assert get_family_entry("X-1") is None
    assert get_family_profile("X-1") is None


def test_current_forms_have_no_period_label_schema() -> None:
    assert EIGHT_K_CHECKBOX_SCHEMA.report_period_companion is None
    assert EIGHT_K_CHECKBOX_SCHEMA.report_period_transition is None
    assert SIX_K_CHECKBOX_SCHEMA.report_period_companion is None
    assert SIX_K_CHECKBOX_SCHEMA.report_period_transition is None


def test_ownership_forms_have_catalog_entries() -> None:
    for form in ("3", "4", "5", "3/A", "4/A", "5/A"):
        entry = get_family_entry(form)
        assert entry is not None
        assert entry.cover_checkbox_schema is None
        profile = get_family_profile(form)
        assert profile is not None
        assert profile.family == form.removesuffix("/A")


@pytest.mark.parametrize("form", ["10-K", "4", "144", "D", "13D", "13G"])
def test_primary_recovery_families_have_lazy_index_triggers(form: str) -> None:
    trigger = get_lazy_index_trigger(form)
    assert trigger == (f"{form}.exact_form", "1")


def test_unconfigured_family_has_no_lazy_index_trigger() -> None:
    assert get_lazy_index_trigger("6-K") is None


def test_form_15_entry_registered_with_schema_and_no_items() -> None:
    entry = get_family_entry("15-12B")
    assert entry is not None
    assert entry.family == "15"
    assert entry.profile is PROFILE_FORM_15
    assert entry.cover_checkbox_schema is FORM_15_CHECKBOX_SCHEMA
    assert entry.taxonomy_items == ()


def test_form_12b25_entry_registered_with_schema_and_part_items() -> None:
    entry = get_family_entry("NT 10-K")
    assert entry is not None
    assert entry.family == "12B-25"
    assert entry.profile is PROFILE_FORM_12B25
    assert entry.cover_checkbox_schema is FORM_12B25_CHECKBOX_SCHEMA
    assert entry.taxonomy_items == FORM_12B25_ITEMS


def test_form_14a_entry_registered_with_schema_and_items() -> None:
    entry = get_family_entry("DEF 14C")
    assert entry is not None
    assert entry.family == "14A"
    assert entry.profile is PROFILE_FORM_14A
    assert entry.cover_checkbox_schema is FORM_14A_CHECKBOX_SCHEMA
    assert entry.taxonomy_items == FORM_14A_ITEMS
    assert get_family_entry("PRE 14A") is entry


def test_form_424b_entry_registered_without_schema_with_items() -> None:
    entry = get_family_entry("424B2")
    assert entry is not None
    assert entry.family == "424B"
    assert entry.profile is PROFILE_FORM_424B
    assert entry.cover_checkbox_schema is None
    assert entry.taxonomy_items == FORM_424B_ITEMS
    assert get_family_entry("424A") is entry
    assert get_family_entry("424B5") is entry


def test_form_fwp_entry_registered_without_schema_with_items() -> None:
    entry = get_family_entry("FWP")
    assert entry is not None
    assert entry.family == "FWP"
    assert entry.profile is PROFILE_FORM_FWP
    assert entry.cover_checkbox_schema is None
    assert entry.taxonomy_items == FORM_FWP_ITEMS


def test_form_425_entry_registered_without_schema_or_items() -> None:
    entry = get_family_entry("425")
    assert entry is not None
    assert entry.family == "425"
    assert entry.profile is PROFILE_FORM_425
    assert entry.cover_checkbox_schema is None
    assert not entry.taxonomy_items


def test_form_f1_entry_registered_with_schema_and_items() -> None:
    entry = get_family_entry("F-1")
    assert entry is not None
    assert entry.family == "F-1"
    assert entry.profile is PROFILE_FORM_F1
    assert entry.cover_checkbox_schema is FORM_F1_CHECKBOX_SCHEMA
    assert entry.taxonomy_items == FORM_F1_ITEMS
    assert get_family_entry("F-1/A") is entry
    assert get_family_entry("F-1MEF") is entry


def test_form_f2_entry_registered_as_variant_of_f1_package() -> None:
    entry = get_family_entry("F-2/A")
    assert entry is not None
    assert entry.family == "F-2"
    assert entry.profile is PROFILE_FORM_F2
    assert entry.cover_checkbox_schema is FORM_F2_CHECKBOX_SCHEMA
    assert entry.taxonomy_items == FORM_F2_ITEMS


def test_form_f3_entry_registered_with_schema_and_items() -> None:
    entry = get_family_entry("F-3ASR")
    assert entry is not None
    assert entry.family == "F-3"
    assert entry.profile is PROFILE_FORM_F3
    assert entry.cover_checkbox_schema is FORM_F3_CHECKBOX_SCHEMA
    assert entry.taxonomy_items == FORM_F3_ITEMS
    assert get_family_entry("F-3D") is entry
    assert get_family_entry("F-3DPOS") is entry


def test_form_f4_entry_registered_with_schema_and_items() -> None:
    entry = get_family_entry("F-4 POS")
    assert entry is not None
    assert entry.family == "F-4"
    assert entry.profile is PROFILE_FORM_F4
    assert entry.cover_checkbox_schema is FORM_F4_CHECKBOX_SCHEMA
    assert entry.taxonomy_items == FORM_F4_ITEMS
    assert get_family_entry("F-4MEF") is entry


def test_40f_and_suppl_aliases_resolve_to_step_10a_profiles() -> None:
    # Step 10 registered the aliases; Step 10A landed the profiles.
    from edgar_sec.domain.forms.common.aliases import resolve_alias

    assert resolve_alias("40-F") == "40-F"
    assert resolve_alias("40-F/A") == "40-F"
    assert resolve_alias("SUPPL") == "SUPPL"
    assert get_family_entry("40-F") is not None
    assert get_family_entry("SUPPL") is not None


def test_mjds_entries_registered_with_shared_package() -> None:
    cases = (
        ("F-7", PROFILE_FORM_F7, FORM_F7_CHECKBOX_SCHEMA, FORM_F7_ITEMS),
        ("F-8", PROFILE_FORM_F8, FORM_F8_CHECKBOX_SCHEMA, FORM_F8_ITEMS),
        ("F-9", PROFILE_FORM_F9, FORM_F9_CHECKBOX_SCHEMA, FORM_F9_ITEMS),
        ("F-10", PROFILE_FORM_F10, FORM_F10_CHECKBOX_SCHEMA, FORM_F10_ITEMS),
        ("F-80", PROFILE_FORM_F80, FORM_F80_CHECKBOX_SCHEMA, FORM_F80_ITEMS),
    )
    for family, profile, schema, items in cases:
        entry = get_family_entry(family)
        assert entry is not None
        assert entry.family == family
        assert entry.profile is profile
        assert entry.cover_checkbox_schema is schema
        assert entry.taxonomy_items == items
    assert get_family_entry("F-8/A") is get_family_entry("F-8")
    assert get_family_entry("F-9 POS") is get_family_entry("F-9")
    assert get_family_entry("F-10EF") is get_family_entry("F-10")


def test_form_40f_entry_registered_with_schema_and_no_items() -> None:
    entry = get_family_entry("40-F/A")
    assert entry is not None
    assert entry.family == "40-F"
    assert entry.profile is PROFILE_FORM_40F
    assert entry.cover_checkbox_schema is FORM_40F_CHECKBOX_SCHEMA
    assert entry.taxonomy_items == ()


def test_form_suppl_entry_registered_without_schema_or_items() -> None:
    entry = get_family_entry("SUPPL")
    assert entry is not None
    assert entry.family == "SUPPL"
    assert entry.profile is PROFILE_FORM_SUPPL
    assert entry.cover_checkbox_schema is None
    assert entry.taxonomy_items == ()


def test_form_f6_entry_registered_with_schema_and_items() -> None:
    entry = get_family_entry("F-6EF")
    assert entry is not None
    assert entry.family == "F-6"
    assert entry.profile is PROFILE_FORM_F6
    assert entry.cover_checkbox_schema is FORM_F6_CHECKBOX_SCHEMA
    assert entry.taxonomy_items == FORM_F6_ITEMS
    assert get_family_entry("F-6 POS") is entry


def test_form_fn_entry_registered_with_schema_and_no_items() -> None:
    entry = get_family_entry("F-N/A")
    assert entry is not None
    assert entry.family == "F-N"
    assert entry.profile is PROFILE_FORM_FN
    assert entry.cover_checkbox_schema is FORM_FN_CHECKBOX_SCHEMA
    assert entry.taxonomy_items == ()


def test_form_11k_entry_registered_with_schema_and_items() -> None:
    entry = get_family_entry("11-KT")
    assert entry is not None
    assert entry.family == "11-K"
    assert entry.profile is PROFILE_FORM_11K
    assert entry.cover_checkbox_schema is FORM_11K_CHECKBOX_SCHEMA
    assert entry.taxonomy_items == FORM_11K_ITEMS
    assert get_family_entry("11-K/A") is entry


def test_rega_entries_registered_without_schemas() -> None:
    from edgar_sec.domain.forms.families.form_rega.processing import (
        PROFILE_REGA_ANNUAL,
        PROFILE_REGA_CURRENT,
        PROFILE_REGA_EXIT,
        PROFILE_REGA_OFFERING,
        PROFILE_REGA_SEMI_ANNUAL,
    )
    from edgar_sec.domain.forms.families.form_rega.taxonomy import (
        FORM_1SA_ITEMS,
        FORM_1U_ITEMS,
    )

    expected = {
        "1-A": (PROFILE_REGA_OFFERING, ()),
        "1-K": (PROFILE_REGA_ANNUAL, ()),
        "1-Z": (PROFILE_REGA_EXIT, ()),
        "1-SA": (PROFILE_REGA_SEMI_ANNUAL, FORM_1SA_ITEMS),
        "1-U": (PROFILE_REGA_CURRENT, FORM_1U_ITEMS),
    }
    for family, (profile, items) in expected.items():
        entry = get_family_entry(family)
        assert entry is not None
        assert entry.family == family
        assert entry.profile is profile
        assert entry.cover_checkbox_schema is None
        assert entry.taxonomy_items == items
    assert get_family_entry("1-A POS") is get_family_entry("1-A")
    assert get_family_entry("1-A-W") is get_family_entry("1-A")
    assert get_family_entry("1-K/A") is get_family_entry("1-K")
    assert get_family_entry("1-Z/A") is get_family_entry("1-Z")
    assert get_family_entry("1-SA/A") is get_family_entry("1-SA")
    assert get_family_entry("1-U/A") is get_family_entry("1-U")


def test_ars_entry_registered_on_generic_segmentation_profile() -> None:
    from edgar_sec.domain.forms.families.processing_profiles import PROFILE_ARS

    entry = get_family_entry("ARS")
    assert entry is not None
    assert entry.family == "ARS"
    assert entry.profile is PROFILE_ARS
    assert entry.cover_checkbox_schema is None
    assert not entry.taxonomy_items
    assert get_family_entry("ARS/A") is entry


@pytest.mark.parametrize(
    "family,variant",
    [
        ("N-CR", "N-CR/A"),
        ("ATS-N", "ATS-N/UA"),
        ("MA-I", "MA-I/A"),
    ],
)
def test_raw_ride_entries_offer_only_raw(family: str, variant: str) -> None:
    from edgar_sec.domain.forms.common.processing import AcquisitionOperation

    entry = get_family_entry(family)
    assert entry is not None
    assert entry.family == family
    assert entry.profile.allowed_operations == frozenset({AcquisitionOperation.RAW})
    assert entry.profile.preferred_operation is AcquisitionOperation.RAW
    assert entry.profile.report_class is None
    assert entry.cover_checkbox_schema is None
    assert not entry.taxonomy_items
    assert get_family_entry(variant) is entry
