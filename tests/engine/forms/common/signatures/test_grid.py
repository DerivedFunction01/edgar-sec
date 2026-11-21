"""Unit tests for signature grid scanning."""


def test_scan_signature_grid_date_in_signature_row():
    """A date cell in a /s/ row is the signature date, no 'Date' label needed."""
    from edgar_sec.engine.forms.common.signatures.grid import scan_signature_grid

    rows = (("/s/ Ronald G. Heller", "February 27, 2003"),)
    name, date = scan_signature_grid(rows)
    assert name == "Ronald G. Heller"
    assert date == "February 27, 2003"


def test_scan_signature_grid_ignores_prose_date_in_signature_row():
    """A date inside a long prose cell of a /s/ row is not the signature date."""
    from edgar_sec.engine.forms.common.signatures.grid import scan_signature_grid

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
    from edgar_sec.engine.forms.common.signatures.grid import scan_signature_grid

    name, _ = scan_signature_grid((("/s/ Ronald\nG. Heller", "February 27, 2003"),))
    assert name == "Ronald G. Heller"


def test_scan_signature_grid_ruled_conformed_line():
    """A ruled /s/ line carrying name and date in one cell yields both."""
    from edgar_sec.engine.forms.common.signatures.grid import scan_signature_grid

    rows = (
        ("____/s/ David R. Smith  ___________    _10/23/00_",),
        ("**Signature of Reporting Person               Date",),
    )
    name, date = scan_signature_grid(rows)
    assert name == "David R. Smith"
    assert date == "10/23/00"


def test_scan_signature_grid_accented_signer_name():
    """Accented letters in a signer name do not reject it."""
    from edgar_sec.engine.forms.common.signatures.grid import scan_signature_grid

    rows = (("", "/s/ Cheryl W. Grisé\n**Signature of Reporting Person"),)
    name, _ = scan_signature_grid(rows)
    assert name == "Cheryl W. Grisé"


def test_scan_signature_grid_name_buried_after_boilerplate():
    """A /s/ name mid-cell, after boilerplate and tabs, still resolves."""
    from edgar_sec.engine.forms.common.signatures.grid import scan_signature_grid

    rows = (
        (
            "**\tIntentional misstatements or omissions of facts constitute "
            "Federal Criminal Violations.\t\t___/s/ David R. Smith____\t\t1-10-01",
        ),
    )
    name, date = scan_signature_grid(rows)
    assert name == "David R. Smith"
    assert date == "1-10-01"


def test_scan_signature_grid_reversed_conformed_token():
    """A reversed 's/Name' conformed token marks a signature row."""
    from edgar_sec.engine.forms.common.signatures.grid import scan_signature_grid

    rows = (("", "", "s/R. S. Bullmore", "January 8, 2003"),)
    name, date = scan_signature_grid(rows)
    assert name == "R. S. Bullmore"
    assert date == "January 8, 2003"


def test_scan_signature_grid_name_glued_to_label():
    """A name followed directly by the signature label yields the name."""
    from edgar_sec.engine.forms.common.signatures.grid import scan_signature_grid

    rows = (("/s/ Jean R. Hale-**Signature of Reporting Person-\t02/12/03-Date",),)
    name, date = scan_signature_grid(rows)
    assert name == "Jean R. Hale"
    assert date == "02/12/03"


def test_scan_strict_dates_ignores_header_date_rows() -> None:
    from edgar_sec.engine.forms.common.signatures.grid import scan_signature_grid

    rows = (
        ("2. Date of Event Requiring Statement (Month/Day/Year)\n12/11/2002",),
        ("**Signature of Reporting Person\n/s/ Jane Q Roe", "Date\n03/04/2003"),
    )
    _name, loose_date = scan_signature_grid(rows)
    assert loose_date == "12/11/2002"
    name, strict_date = scan_signature_grid(rows, strict_dates=True)
    assert name == "Jane Q Roe"
    assert strict_date == "03/04/2003"
