"""Unit tests for signature candidate and block extraction."""

from edgar_sec.engine.forms.common.signatures.blocks import (
    extract_signature_block,
    extract_signature_candidate,
    find_preceding_signature_date,
)


def test_extract_signature_candidate():
    """Verify signature candidate name and date parsing."""
    text = "/s/ Robert Taylor\nNovember 15, 2023\n"
    name, date = extract_signature_candidate(text)
    assert name == "Robert Taylor"
    assert date == "November 15, 2023"


def test_extract_signature_block():
    """Verify structured signature block extraction."""
    block_text = "/s/ John Doe\nBy: Jane Smith, Attorney-in-Fact\n"
    block = extract_signature_block(block_text)
    assert block is not None
    assert block.is_conformed is True
    assert len(block.signatories) >= 1


def test_candidate_date_anchored_to_signature_label():
    """With a signature label present, an earlier stray date is not the sig date."""
    from edgar_sec.engine.forms.common.signatures.blocks import (
        extract_signature_candidate,
    )

    text = (
        "shares traded 02/24/2003 in the open market\n"
        "row one\nrow two\nrow three\nrow four\n"
        "SIGNATURE OF REPORTING PERSON\n"
        "Vernon E. Jordan, Jr.\n"
    )
    name, date = extract_signature_candidate(text)
    assert name == "Vernon E. Jordan, Jr."
    assert date is None


def test_candidate_finds_ruled_full_date_below_label():
    """A full date wrapped in underscore rules still anchors to the block."""
    from edgar_sec.engine.forms.common.signatures.blocks import (
        extract_signature_candidate,
    )

    text = "______J. Peter Jeffrey ___\n**Signature of Reporting Person\n____May 9, 2001_____\nDate\n"
    name, date = extract_signature_candidate(text)
    assert name == "J. Peter Jeffrey"
    assert date == "May 9, 2001"


def test_candidate_surname_first_conformed_name():
    """A 'Surname, Given' conformed signature keeps the full filed name."""
    from edgar_sec.engine.forms.common.signatures.blocks import (
        extract_signature_candidate,
    )

    name, date = extract_signature_candidate("/S/ Hernquist, Thomas K. DATE 04/29/03")
    assert name == "Hernquist, Thomas K."
    assert date == "04/29/03"


def test_candidate_bare_conformed_prefix_with_spelled_date() -> None:
    from edgar_sec.engine.forms.common.signatures.blocks import (
        extract_signature_candidate,
    )

    name, date = extract_signature_candidate(
        "By: s/ Roger S. Begelman    June 11, 2001\n"
        "-----\n**Signature of Reporting Person    Date\n"
    )
    assert name == "Roger S. Begelman"
    assert date == "June 11, 2001"


def test_candidate_name_on_line_above_label() -> None:
    from edgar_sec.engine.forms.common.signatures.blocks import (
        extract_signature_candidate,
    )

    name, _date = extract_signature_candidate(
        "-----\nHilton H. Howell, Jr.    Date\n**Signature of Reporting Person\n"
    )
    assert name == "Hilton H. Howell, Jr."


def test_candidate_date_on_line_after_conformed_line() -> None:
    from edgar_sec.engine.forms.common.signatures.blocks import (
        extract_signature_candidate,
    )

    name, date = extract_signature_candidate("/s/ James E. McKee\n\n1/28/03\n")
    assert name == "James E. McKee"
    assert date == "1/28/03"
    _name, date2 = extract_signature_candidate(
        "/s/ Robert H. Young,\nAttorney-in-fact    2/13/03\n"
    )
    assert date2 == "2/13/03"


def test_candidate_date_on_header_line_above_label() -> None:
    from edgar_sec.engine.forms.common.signatures.blocks import (
        extract_signature_candidate,
    )

    name, date = extract_signature_candidate(
        "John E. J. King    09/7/2001\n-----\n**Signature of Reporting Person    Date\n"
    )
    assert name == "John E. J. King"
    assert date == "09/7/2001"


def test_candidate_rejects_month_word_as_name() -> None:
    from edgar_sec.engine.forms.common.signatures.blocks import (
        extract_signature_candidate,
    )
    from edgar_sec.engine.forms.common.signatures.names import (
        is_valid_signature_name,
    )

    assert not is_valid_signature_name("APRIL")
    name, date = extract_signature_candidate(
        "FLORENCE MEI FONG CHOONG /S/    APRIL 30, 2003\n"
        "**Signature of Reporting Person    Date\n"
    )
    assert name != "APRIL"
    assert date == "APRIL 30, 2003"


def test_candidate_ignores_plan_statement_as_of_date() -> None:
    from edgar_sec.engine.forms.common.signatures.blocks import (
        extract_signature_candidate,
    )

    _name, date = extract_signature_candidate(
        "**Signature of Reporting Person    Date\n"
        "By: Patricia A. Bell\nFor: Kathelen Spencer\n"
        "The information in this report is based on a plan statement "
        "dated as of December 31, 2002.\n"
    )
    assert date is None


def test_find_preceding_signature_date_reads_nearest_date_line():
    lines = ["SIGNATURE", "November 2, 2026", "By:"]
    assert find_preceding_signature_date(lines) == "November 2, 2026"


def test_find_preceding_signature_date_skips_undated_lines():
    lines = ["Dated: November 2, 2026", "Some other text", ""]
    assert find_preceding_signature_date(lines) == "November 2, 2026"


def test_find_preceding_signature_date_respects_lookback_window():
    lines = ["November 2, 2026"] + ["filler"] * 10
    assert find_preceding_signature_date(lines) is None
    assert find_preceding_signature_date(["filler", "text only"]) is None


def test_extract_signature_block_accepts_quoted_conformed_name():
    from edgar_sec.engine.forms.common.signatures.blocks import (
        extract_signature_block,
    )

    block = extract_signature_block(
        "has caused this certification/notice to be signed on its behalf\n"
        "Date: December 4, 2024  By:  /s/ “Peter Evensen”\n"
        "President and Chief Executive Officer\n"
    )
    assert block is not None
    assert [s.name for s in block.signatories] == ["Peter Evensen"]
    assert block.is_conformed is True
