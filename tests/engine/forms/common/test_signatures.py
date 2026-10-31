"""Unit tests for engine signature parsing utilities."""

from edgar_sec.domain.forms.common.signatures import DelegationKind
from edgar_sec.engine.forms.common.signatures import (
    CONFORMED_SIGNATURE_RE,
    NOTARY_JURAT_RE,
    OFFICER_TITLE_RE,
    POA_AUTH_RE,
    SIGNATORY_ROLE_RE,
    clean_signature_name,
    extract_signature_block,
    extract_signature_candidate,
    is_valid_signature_name,
    parse_conformed_signature,
    resolve_delegated_signer,
)


def test_clean_signature_name():
    """Verify stripping of dashes, labels, and markup."""
    raw = "___ /s/ Jane Doe ___"
    assert clean_signature_name(raw) == "Jane Doe"
    raw_by = "By: John Smith"
    assert clean_signature_name(raw_by) == "John Smith"
    repeated = "James P. Ryan James P. Ryan"
    assert clean_signature_name(repeated) == "James P. Ryan"


def test_parse_conformed_signature():
    """Verify detection of /s/ markup."""
    text_conf = "/s/ Alice Johnson"
    name, is_conf = parse_conformed_signature(text_conf)
    assert name == "Alice Johnson"
    assert is_conf is True

    text_plain = "Bob Williams"
    name2, is_conf2 = parse_conformed_signature(text_plain)
    assert name2 == "Bob Williams"
    assert is_conf2 is False


def test_resolve_delegated_signer():
    """Verify detection of power of attorney delegations."""
    poa_text = "Jane Doe, Attorney-in-Fact"
    name, kind, agent = resolve_delegated_signer(poa_text)
    assert kind == DelegationKind.POWER_OF_ATTORNEY
    assert agent == "Jane Doe"


def test_extract_signature_candidate():
    """Verify signature candidate name and date parsing."""
    text = "/s/ Robert Taylor\nNovember 15, 2023\n"
    name, date = extract_signature_candidate(text)
    assert name == "Robert Taylor"
    assert date == "November 15, 2023"


def test_signature_regexes():
    """Verify compiled signature, role, and notary regexes."""
    assert bool(CONFORMED_SIGNATURE_RE.search("/s/ Jane"))
    assert bool(NOTARY_JURAT_RE.search("Subscribed and sworn before me"))
    assert bool(OFFICER_TITLE_RE.search("Vice President"))
    assert bool(SIGNATORY_ROLE_RE.search("Managing Member"))
    assert bool(POA_AUTH_RE.search("Know all by these presents"))


def test_extract_signature_block():
    """Verify structured signature block extraction."""
    block_text = "/s/ John Doe\nBy: Jane Smith, Attorney-in-Fact\n"
    block = extract_signature_block(block_text)
    assert block is not None
    assert block.is_conformed is True
    assert len(block.signatories) >= 1


def test_is_valid_signature_name():
    """Verify acceptance of person names and rejection of boilerplate."""
    assert is_valid_signature_name("John Doe") is True
    assert is_valid_signature_name("Table I") is False
    assert is_valid_signature_name("TABLE II") is False
    assert is_valid_signature_name("Table 1") is False
    assert is_valid_signature_name("Table 2") is False


def test_scan_signature_grid_date_in_signature_row():
    """A date cell in a /s/ row is the signature date, no 'Date' label needed."""
    from edgar_sec.engine.forms.common.signatures import scan_signature_grid

    rows = (("/s/ Ronald G. Heller", "February 27, 2003"),)
    name, date = scan_signature_grid(rows)
    assert name == "Ronald G. Heller"
    assert date == "February 27, 2003"


def test_scan_signature_grid_ignores_prose_date_in_signature_row():
    """A date inside a long prose cell of a /s/ row is not the signature date."""
    from edgar_sec.engine.forms.common.signatures import scan_signature_grid

    rows = (
        (
            "Explanation of Responses: the plan adopted on March 3, 2003 by the board",
            "/s/ Jane Doe",
            "February 27, 2003",
        ),
    )
    name, date = scan_signature_grid(rows)
    assert name == "Jane Doe"
    assert date == "February 27, 2003"


def test_scan_signature_grid_name_split_across_lines():
    """A name wrapped across lines inside one cell still resolves."""
    from edgar_sec.engine.forms.common.signatures import scan_signature_grid

    name, _ = scan_signature_grid((("/s/ Ronald\nG. Heller", "February 27, 2003"),))
    assert name == "Ronald G. Heller"


def test_scan_signature_grid_ruled_conformed_line():
    """A ruled /s/ line carrying name and date in one cell yields both."""
    from edgar_sec.engine.forms.common.signatures import scan_signature_grid

    rows = (
        ("____/s/ David R. Smith  ___________    _10/23/00_",),
        ("**Signature of Reporting Person               Date",),
    )
    name, date = scan_signature_grid(rows)
    assert name == "David R. Smith"
    assert date == "10/23/00"


def test_scan_signature_grid_accented_signer_name():
    """Accented letters in a signer name do not reject it."""
    from edgar_sec.engine.forms.common.signatures import scan_signature_grid

    rows = (("", "/s/ Cheryl W. Grisé\n**Signature of Reporting Person"),)
    name, _ = scan_signature_grid(rows)
    assert name == "Cheryl W. Grisé"


def test_scan_signature_grid_name_buried_after_boilerplate():
    """A /s/ name mid-cell, after boilerplate and tabs, still resolves."""
    from edgar_sec.engine.forms.common.signatures import scan_signature_grid

    rows = (
        (
            "**\tIntentional misstatements or omissions of facts constitute "
            "Federal Criminal Violations.\t\t___/s/ David R. Smith____\t\t1-10-01",
        ),
    )
    name, date = scan_signature_grid(rows)
    assert name == "David R. Smith"
    assert date == "1-10-01"


def test_candidate_date_anchored_to_signature_label():
    """With a signature label present, an earlier stray date is not the sig date."""
    from edgar_sec.engine.forms.common.signatures import extract_signature_candidate

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
    from edgar_sec.engine.forms.common.signatures import extract_signature_candidate

    text = "______J. Peter Jeffrey ___\n**Signature of Reporting Person\n____May 9, 2001_____\nDate\n"
    name, date = extract_signature_candidate(text)
    assert name == "J. Peter Jeffrey"
    assert date == "May 9, 2001"


def test_candidate_surname_first_conformed_name():
    """A 'Surname, Given' conformed signature keeps the full filed name."""
    from edgar_sec.engine.forms.common.signatures import extract_signature_candidate

    name, date = extract_signature_candidate("/S/ Hernquist, Thomas K. DATE 04/29/03")
    assert name == "Hernquist, Thomas K."
    assert date == "04/29/03"


def test_scan_signature_grid_reversed_conformed_token():
    """A reversed 's/Name' conformed token marks a signature row."""
    from edgar_sec.engine.forms.common.signatures import scan_signature_grid

    rows = (("", "", "s/R. S. Bullmore", "January 8, 2003"),)
    name, date = scan_signature_grid(rows)
    assert name == "R. S. Bullmore"
    assert date == "January 8, 2003"


def test_scan_signature_grid_name_glued_to_label():
    """A name followed directly by the signature label yields the name."""
    from edgar_sec.engine.forms.common.signatures import scan_signature_grid

    rows = (("/s/ Jean R. Hale-**Signature of Reporting Person-\t02/12/03-Date",),)
    name, date = scan_signature_grid(rows)
    assert name == "Jean R. Hale"
    assert date == "02/12/03"


def test_candidate_bare_conformed_prefix_with_spelled_date() -> None:
    from edgar_sec.engine.forms.common.signatures import extract_signature_candidate

    name, date = extract_signature_candidate(
        "By: s/ Roger S. Begelman    June 11, 2001\n"
        "-----\n**Signature of Reporting Person    Date\n"
    )
    assert name == "Roger S. Begelman"
    assert date == "June 11, 2001"


def test_candidate_name_on_line_above_label() -> None:
    from edgar_sec.engine.forms.common.signatures import extract_signature_candidate

    name, _date = extract_signature_candidate(
        "-----\nHilton H. Howell, Jr.    Date\n**Signature of Reporting Person\n"
    )
    assert name == "Hilton H. Howell, Jr."


def test_candidate_date_on_line_after_conformed_line() -> None:
    from edgar_sec.engine.forms.common.signatures import extract_signature_candidate

    name, date = extract_signature_candidate("/s/ James E. McKee\n\n1/28/03\n")
    assert name == "James E. McKee"
    assert date == "1/28/03"
    _name, date2 = extract_signature_candidate(
        "/s/ Robert H. Young,\nAttorney-in-fact    2/13/03\n"
    )
    assert date2 == "2/13/03"


def test_candidate_date_on_header_line_above_label() -> None:
    from edgar_sec.engine.forms.common.signatures import extract_signature_candidate

    name, date = extract_signature_candidate(
        "John E. J. King    09/7/2001\n-----\n**Signature of Reporting Person    Date\n"
    )
    assert name == "John E. J. King"
    assert date == "09/7/2001"


def test_candidate_rejects_month_word_as_name() -> None:
    from edgar_sec.engine.forms.common.signatures import (
        extract_signature_candidate,
        is_valid_signature_name,
    )

    assert not is_valid_signature_name("APRIL")
    name, date = extract_signature_candidate(
        "FLORENCE MEI FONG CHOONG /S/    APRIL 30, 2003\n"
        "**Signature of Reporting Person    Date\n"
    )
    assert name != "APRIL"
    assert date == "APRIL 30, 2003"


def test_scan_strict_dates_ignores_header_date_rows() -> None:
    from edgar_sec.engine.forms.common.signatures import scan_signature_grid

    rows = (
        ("2. Date of Event Requiring Statement (Month/Day/Year)\n12/11/2002",),
        ("**Signature of Reporting Person\n/s/ Jane Q Roe", "Date\n03/04/2003"),
    )
    _name, loose_date = scan_signature_grid(rows)
    assert loose_date == "12/11/2002"
    name, strict_date = scan_signature_grid(rows, strict_dates=True)
    assert name == "Jane Q Roe"
    assert strict_date == "03/04/2003"


def test_clean_name_drops_title_segment_after_ampersand() -> None:
    from edgar_sec.engine.forms.common.signatures import (
        extract_clean_signatory_name,
        is_valid_signature_name,
    )

    assert (
        extract_clean_signatory_name("Christian S. Schade & Chief Financial Officer")
        == "Christian S. Schade"
    )
    assert (
        extract_clean_signatory_name("Dan Goldstein & Chief Executive Officer")
        == "Dan Goldstein"
    )
    assert extract_clean_signatory_name("Chief Financial Officer") is None
    assert not is_valid_signature_name("Attorney-in-Fact for")


def test_candidate_ignores_plan_statement_as_of_date() -> None:
    from edgar_sec.engine.forms.common.signatures import extract_signature_candidate

    _name, date = extract_signature_candidate(
        "**Signature of Reporting Person    Date\n"
        "By: Patricia A. Bell\nFor: Kathelen Spencer\n"
        "The information in this report is based on a plan statement "
        "dated as of December 31, 2002.\n"
    )
    assert date is None
