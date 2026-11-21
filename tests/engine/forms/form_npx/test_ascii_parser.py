"""Tests for the Form N-PX text-era parser."""

from edgar_sec.engine.forms.form_npx.ascii_parser import parse_npx_text

_SGML = b"""<DOCUMENT>
<TYPE>N-PX
<TEXT>
                                   FORM N-PX
               ANNUAL REPORT OF PROXY VOTING RECORD OF REGISTERED
                         MANAGEMENT INVESTMENT COMPANY
                   Investment Company Act file number: 811-41
                    General American Investors Company, Inc.
               (Exact name of registrant as specified in charter)
Date of reporting period:  July 1, 2003 - June 30, 2004
Item 1.  Proxy Voting Record.
<TABLE>
<CAPTION>
ALKERMES, INC.
CUSIP/CINS: 01642T
Meeting Type: ANNUAL
Ticker:  ALKS
Meeting Date: 09-Sep-03
Item            Proposal                                        Type                Vote
----------------------------------------------------------------------------------------------------------
<S>                                                             <C>                 <C>
1   DIRECTOR                                                    Mgmt
    1     FLOYD E. BLOOM                                                            For            For
    2     ROBERT A. BREYER                                                          For            For
</TABLE>
</TEXT>
</DOCUMENT>
"""

_COLUMNAR = b"""<html><body>
<table>
<tr><td>ISSUER NAME</td><td>TICKER</td><td>CUSIP</td><td>MTG DATE</td>
<td>Proposal</td><td>Type</td><td>MTG TYPE</td><td>Voted?</td><td>Vote</td>
<td>For/Agnst Mgmt</td></tr>
<tr><td>State</td><td>Street</td><td>STT</td><td>857477103</td>
<td>4/21/04</td><td>Annual</td></tr>
<tr><td>1.01</td><td>Elect Directors</td><td>MGMT</td><td>YES</td>
<td>FOR</td><td>FOR</td></tr>
<tr><td>1.02</td><td>Elect Directors</td><td>MGMT</td><td>YES</td>
<td>FOR</td><td>FOR</td></tr>
</table>
</body></html>
"""


def test_parse_sgml_block_layout() -> None:
    """The SGML issuer-block layout yields cover and vote rows."""
    doc = parse_npx_text(_SGML)
    assert doc.file_number == "811-41"
    assert doc.period_of_report == "06/30/2004"
    assert doc.reporting_person_name == "General American Investors Company, Inc."
    assert len(doc.vote_rows) == 2
    row = doc.vote_rows[0]
    assert row.issuer_name == "ALKERMES, INC."
    assert row.meeting_date == "09/09/2003"
    assert row.vote_description == "FLOYD E. BLOOM"
    assert row.how_voted == ("For",)


_FILE_NO_COVER = b"""<DOCUMENT>
<TYPE>N-PX
<TEXT>
                                        FORM N-PX
                        Investment Company Act File No. 811-21539
               First Trust Senior Floating Rate Income Fund II
              -------------------------------------------------------------
              Exact Name of Registrant as Specified in Declaration of Trust
                 Date of reporting period: July 1, 2003 - June 30, 2004
</TEXT>
</DOCUMENT>
"""

_SECURITY_BLOCK = b"""<DOCUMENT>
<TYPE>N-PX
<TEXT>
Item 1.  Proxy Voting Record.
<TABLE>
<CAPTION>
<S>    <C>                               <C>                       <C>        <C>
ADAMS EXPRESS COMPANY
       Security  006212104               Meeting Type   Annual
       Ticker Symbol ADX                 Meeting Date   4/27/2005
Item            Proposal                                           Type       Vote        For/Against Management
----------------------------------------------------------------------------------------------------------
01     DIRECTOR                                                    Mgmt
 1     ENRIQUE R. AZAC                                                        For         For
 2     PHYLLIS O. BONANNO                                                     For         For
</TABLE>
</TEXT>
</DOCUMENT>
"""

_SPLIT_COVER_HTM = b"""<html><body>
<p>Investment Company Act
file number: 811-22632</p>
<p>reporting period:</p><p><u>6/30/12</u></p>
</body></html>
"""


def test_parse_file_no_cover_variant() -> None:
    """The File No. cover variant yields number, name, and period."""
    doc = parse_npx_text(_FILE_NO_COVER)
    assert doc.file_number == "811-21539"
    assert doc.reporting_person_name == (
        "First Trust Senior Floating Rate Income Fund II"
    )
    assert doc.period_of_report == "06/30/2004"


def test_parse_security_anchor_block() -> None:
    """Issuer blocks anchored on a Security line yield vote rows."""
    doc = parse_npx_text(_SECURITY_BLOCK)
    assert len(doc.vote_rows) == 2
    row = doc.vote_rows[0]
    assert row.issuer_name == "ADAMS EXPRESS COMPANY"
    assert row.cusip == "006212104"
    assert row.meeting_date == "04/27/2005"
    assert row.vote_description == "ENRIQUE R. AZAC"
    assert row.how_voted == ("For",)


def test_parse_split_phrase_cover_htm() -> None:
    """Cover phrases split across lines or cells still extract."""
    doc = parse_npx_text(_SPLIT_COVER_HTM)
    assert doc.file_number == "811-22632"
    assert doc.period_of_report == "06/30/2012"


def test_parse_columnar_layout() -> None:
    """The columnar HTML table layout yields vote rows per proposal."""
    doc = parse_npx_text(_COLUMNAR)
    assert len(doc.vote_rows) == 2
    row = doc.vote_rows[0]
    assert row.issuer_name == "State Street"
    assert row.cusip == "857477103"
    assert row.meeting_date == "04/21/2004"
    assert row.vote_description == "Elect Directors"
    assert row.how_voted == ("FOR",)
