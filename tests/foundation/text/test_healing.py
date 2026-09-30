"""Unit tests for edgar_sec.foundation.text.healing."""

from __future__ import annotations

from edgar_sec.foundation.text.healing import (
    PhraseSequenceRule,
    heal_split_lines,
    normalize_whitespace_and_tabs,
    should_join_two_lines,
)


def test_normalize_whitespace_and_tabs() -> None:
    raw = "UNITED\t\tSTATES\r\n\t  \t\r\nSECURITIES   AND   EXCHANGE   COMMISSION\n\n\nWASHINGTON, D.C."
    cleaned = normalize_whitespace_and_tabs(raw)
    expected = "UNITED STATES\n\nSECURITIES AND EXCHANGE COMMISSION\n\nWASHINGTON, D.C."
    assert cleaned == expected


def test_should_join_two_lines_and_negative_guards() -> None:
    rules = [
        PhraseSequenceRule(
            name="sec_agency",
            tokens=["united", "states", "securities", "and", "exchange", "commission"],
            anchor=["united", "securities", "commission"],
        ),
        PhraseSequenceRule(
            name="fiscal_period",
            tokens=["for", "the", "fiscal", "year", "ended"],
            anchor=["fiscal"],
        ),
    ]

    # Positive joins
    assert (
        should_join_two_lines(
            "UNITED STATES", "SECURITIES AND EXCHANGE COMMISSION", rules
        )
        is True
    )
    assert (
        should_join_two_lines("For the fiscal", "year ended December 31, 2024", rules)
        is True
    )

    # Negative boundary guards
    assert (
        should_join_two_lines("Common Stock", "(1) has filed all reports", rules)
        is False
    )
    assert (
        should_join_two_lines("Securities", "[X] ANNUAL REPORT PURSUANT", rules)
        is False
    )
    assert should_join_two_lines("Address", "<TABLE>", rules) is False
    assert (
        should_join_two_lines(
            "For the transition period from to",
            "Commission File Number: 001-32947",
            rules,
        )
        is False
    )

    # Caption vs value separation
    assert (
        should_join_two_lines(
            "270 Park Avenue", "(Address of Principal Executive Offices)", rules
        )
        is False
    )


def test_heal_split_lines_end_to_end() -> None:
    rules = [
        PhraseSequenceRule(
            name="sec_banner",
            tokens=["united", "states", "securities", "and", "exchange", "commission"],
            anchor=["securities"],
        ),
        PhraseSequenceRule(
            name="fiscal_period",
            tokens=["for", "the", "fiscal", "year", "ended"],
            anchor=["fiscal"],
        ),
    ]

    lines = [
        "UNITED STATES",
        "SECURITIES AND EXCHANGE COMMISSION",
        "WASHINGTON, D.C. 20549",
        "FORM 10-K",
        "For the fiscal",
        "year ended December 31, 2024",
        "[X] ANNUAL REPORT PURSUANT TO SECTION 13",
    ]

    healed = heal_split_lines(lines, rules)
    assert healed[0] == "UNITED STATES SECURITIES AND EXCHANGE COMMISSION"
    assert healed[1] == "WASHINGTON, D.C. 20549"
    assert healed[2] == "FORM 10-K"
    assert healed[3] == "For the fiscal year ended December 31, 2024"
    assert healed[4] == "[X] ANNUAL REPORT PURSUANT TO SECTION 13"


def test_heal_split_lines_preserves_cover_orientation() -> None:
    rules = [
        PhraseSequenceRule(
            name="sec_banner",
            tokens=["united", "states", "securities", "and", "exchange", "commission"],
            anchor=["securities"],
        ),
    ]
    lines = [
        "    UNITED STATES",
        "    SECURITIES AND EXCHANGE COMMISSION",
    ]
    healed = heal_split_lines(lines, rules)
    assert healed == ["    UNITED STATES SECURITIES AND EXCHANGE COMMISSION"]
