from __future__ import annotations

from edgar_sec.engine.forms.beneficial_ownership.cover_value_diagnostics import (
    cover_field_has_layout_residue,
    has_descriptive_numeric_qualifier,
    is_eight_character_cusip,
    parsed_field_boilerplate_match,
    two_character_codes,
)


def test_descriptive_numeric_values_require_specific_source_qualifiers() -> None:
    assert has_descriptive_numeric_qualifier("28,833,831 shares (including warrants)")
    assert has_descriptive_numeric_qualifier("49,724,330 Shares *")
    assert has_descriptive_numeric_qualifier("Less than 1%")
    assert has_descriptive_numeric_qualifier("8,302,280[1]")
    assert has_descriptive_numeric_qualifier("18,000,000 COMMON")
    assert not has_descriptive_numeric_qualifier("12 shares and more")


def test_short_cusip_recognizes_eight_character_source_values() -> None:
    assert is_eight_character_cusip("00133968")
    assert not is_eight_character_cusip("0013396")
    assert not is_eight_character_cusip("001339689")


def test_cover_layout_residue_detects_repeated_table_row_labels() -> None:
    assert cover_field_has_layout_residue("soleDispositivePower", "9 906,245")
    assert cover_field_has_layout_residue("sharedVotingPower", "None : With")
    assert cover_field_has_layout_residue(
        "aggregateAmountOwned", "BY EACH PERSON 1,421,300"
    )
    assert not cover_field_has_layout_residue("soleVotingPower", "906,245")


def test_two_character_codes_preserves_numeric_fund_codes() -> None:
    assert two_character_codes("(SEE INSTRUCTIONS) 00-Funds of advisory clients") == (
        "00",
    )


def test_parsed_field_boilerplate_uses_shared_phrase_annotations() -> None:
    assert (
        parsed_field_boilerplate_match("Date of original filing") == "Date of original"
    )
    assert parsed_field_boilerplate_match("See instruction\n6 for procedure") == (
        "See instruction\n6 for procedure"
    )
    assert parsed_field_boilerplate_match("I.R.S. Identification No.") == (
        "I.R.S. Identification"
    )
    assert parsed_field_boilerplate_match("SCHEDULE 13D") == "SCHEDULE 13D"
    assert parsed_field_boilerplate_match("ITEM 4. Source of funds") == "ITEM 4."
    assert parsed_field_boilerplate_match("Jane Doe") is None
