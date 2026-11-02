"""Tests for the Form 13F ASCII (pre-2013 text) parser."""

from edgar_sec.engine.forms.form_13f.ascii_parser import parse_form_13f_text

_SAMPLE = """<DOCUMENT>
<TYPE>13F-HR
<SEQUENCE>1
<FILENAME>adx1201.txt
<TEXT>
<Page>

                               UNITED STATES
                    SECURITIES AND EXCHANGE COMMISSION
                          Washington, D.C. 20549
                                 Form 13F
                            Form 13F COVER PAGE
Report for the Calendar Year or Quarter Ended: December 31, 2001
Check here if Amendment [ ]; Amendment Number: ____
This Amendment (Check only one.): [ ] is a restatement.
[ ] adds new holdings entries.

Institutional Investment Manager Filing this Report:
Name:_____The Adams Express Company____
Address: _7 St. Paul Street, Suite 1140
__________Baltimore, MD 21202__________
__________________________________________
Form 13F File Number: 28-597_________
The institutional investment manager filing this report and the
person by whom it is signed hereby represent that the person
signing the report is authorized to submit it, that all
information contained herein is true, correct and complete, and
that it is understood that all required items, statements,
schedules, lists, and tables, are considered integral parts of
this form.
Person Signing this Report on Behalf of Reporting Manager:
Name: ___Christine M. Sloan____
Title: __Assistant Treasurer___
Phone: __(401) 752-5900________
Signature, Place, and Date of Signing:
__(signed)_Christine M. Sloan Baltimore, Md. January 25 2002
[Signature] [City, State] [Date]
Report Type (Check only one.):
[X] 13F HOLDINGS REPORT. (Check here if all holdings of this
reporting manager are reported in this report.)
[ ] 13F NOTICE. (Check here if no holdings reported are in this
report, and all holdings are reported by other reporting
manager(s).)
[ ] 13F COMBINATION REPORT. (Check here if a portion of the
holdings for this reporting manager are reported in this
report and a portion are reported by other reporting
manager(s).)
List of Other Managers Reporting for this Manager:
[If there are no entries in this list, omit this section.]
Form 13F File Number Name
28-____________ ________________________________
[Repeat as necessary.]
<Page>

Form 13F SUMMARY PAGE
Report Summary:
Number of Other Included Managers: __________0____
Form 13F Information Table Entry Total: ____93______
Form 13F Information Table Value Total: $_1,284______
<TABLE>
<CAPTION>
                           FORM 13F INFORMATION TABLE

COLUMN 1                              COLUMN 2   COLUMN 3  COLUMN 4        COLUMN 5        COL. 6 COLUMN 7         COLUMN 8
-------------------------------       --------   --------  --------   ------------------   ------ --------  ----------------------
                                      TITLE OF               VALUE                           -      OTHER
NAME OF ISSUER                         CLASS      CUSIP    (x$1000)                        INVSTM MANAGERS
<S>                                  <C>        <C>        <C>                               T    <C>
                                                                                           DSCRET
                                                                                             N
                                                                                           <C>
                                                                     SHARES/     SH/P PUT/                     VOTING AUTHORITY
                                                                     PRIN.AMT    RN   CALL
                                                                     <C>         <C>  <C>
                                                                                                               SOLE    SHARE NONE
                                                                                                            <C>          D   <C>
                                                                                                                       <C>
ABBOTT LABORATORIES                     COM      002824100    19,513     350,000 SH        SOLE                350,000
AFFYMETRIX INC.                         COM      00826T108     7,928     210,000 SH        SOLE                210,000
AMBAC FINANCIAL GROUP, INC.             COM      023139108    32,945     569,400 SH        SOLE                569,400
AMERICAN HOME PRODUCTS CORP.            COM      026609107    18,408     300,000 SH        SOLE                300,000
AMERICAN INTL. GROUP INC.               COM      026874107    60,294     759,375 SH        SOLE                759,375
APPLERA CORP.                           COM      038020103     8,247     210,000 SH        SOLE                210,000
BJ WHOLESALE CLUB                       COM      05548J106    14,884     337,500 SH        SOLE                337,500
BJ WHOLESALE CLUB                       PUT      05548J956     1,543      35,000       PUT
""".encode()


def test_parse_text_cover_and_summary() -> None:
    """Cover and summary fields come through with dollars normalization."""
    doc = parse_form_13f_text(_SAMPLE)
    assert doc.submission_type == "13F-HR"
    assert doc.manager_name == "The Adams Express Company"
    assert doc.form13f_file_number == "28-597"
    assert doc.report_type == "13F HOLDINGS REPORT"
    assert doc.period_of_report == "December 31, 2001"
    assert doc.other_included_managers_count == 0
    assert doc.table_entry_total == 93
    assert doc.table_value_total == 1284 * 1000


_VERTICAL = b"""<DOCUMENT>
<TYPE>13F-HR
<TEXT>
Form 13F COVER PAGE
Report for the Quarter Ended June 30, 1999

                  AMERICAN FINANCIAL GROUP, INC.
                 One East Fourth Street, Cincinnati, Ohio 45202
     ----------------------------------------------------------------
     (Name and Address of Institutional Investment Manager Filing this Report)

                         Form 13F File Number:  28-4389
Report Type (Check only one.):
|X| 13F HOLDINGS REPORT.
<TABLE>
<CAPTION>
FORM 13F INFORMATION TABLE
COLUMN 1
-------------------------------
NAME OF ISSUER
<S>
COLUMN 3
----------
CUSIP
<C>
ACME CORP
COM
001000000
1,250
10,000
SH
SOLE
10,000
</TABLE>
"""


def test_parse_text_vertical_table_and_old_cover() -> None:
    """Vertical tables assemble rows around bare CUSIP lines."""
    doc = parse_form_13f_text(_VERTICAL)
    assert doc.manager_name == "AMERICAN FINANCIAL GROUP, INC."
    assert doc.report_type == "13F HOLDINGS REPORT"
    assert doc.period_of_report == "June 30, 1999"
    assert len(doc.holdings) == 1
    row = doc.holdings[0]
    assert row.name_of_issuer == "ACME CORP"
    assert row.value == 1250 * 1000
    assert row.shares_or_principal == 10000
    assert row.voting_sole == 10000


def test_parse_text_holdings_rows() -> None:
    """Fixed-column rows slice into typed holdings with era scaling."""
    doc = parse_form_13f_text(_SAMPLE)
    assert len(doc.holdings) == 8
    first = doc.holdings[0]
    assert first.name_of_issuer == "ABBOTT LABORATORIES"
    assert first.title_of_class == "COM"
    assert first.cusip == "002824100"
    assert first.value == 19513 * 1000
    assert first.shares_or_principal == 350000
    assert first.amount_type == "SH"
    assert first.investment_discretion == "SOLE"
    assert first.voting_sole == 350000
    put_rows = [row for row in doc.holdings if row.put_call == "Put"]
    assert len(put_rows) == 1
    assert put_rows[0].cusip == "05548J956"
    assert put_rows[0].shares_or_principal == 35000
