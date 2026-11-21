"""Unit tests for Form 144 ASCII state machine parser."""

from pathlib import Path

from edgar_sec.engine.forms.form144.ascii_parser import parse_ascii_form144


def test_parse_ascii_form144_cover_addresses_phone_and_table_i() -> None:
    sample_text = """
1    (a) NAME OF ISSUER: Adams Diversified Equity Fund, Inc.
     (b) IRS IDENT. NO.: 13-4912740
     (c) S.E.C. FILE NO.: 0000002230
     (d) ADDRESS OF ISSUER STREET CITY STATE ZIP CODE:
     500 East Pratt Street, Suite 1300, Baltimore, MD  21202
     (e) TELEPHONE NO. AREA CODE NUMBER:  (410) 752-5900
2    (a) NAME OF PERSON FOR WHOSE ACCOUNT THE SECURITIES ARE
TO BE SOLD:  Mark E. Stoeckle
     (b) RELATIONSHIP TO ISSUER:  CEO
     (c) ADDRESS STREET CITY STATE ZIP CODE:
     500 East Pratt Street, Baltimore, MD  21202
3    (a) Common Stock
     (c) Number of Shares or Other Units To Be Sold:  21,110

TABLE I: SECURITIES TO BE SOLD
Title of the Class:  Common
Date you Acquired:  2/11/2013
Nature of Acquisition Transaction:  Grant
Name of Person from Whom Acquired: Adams Diversified Equity Fund, Inc.
Amount of Securities Acquired:  41,884
Date of Payment:  2/11/2013
Nature of Payment:  Grant
"""
    sections = parse_ascii_form144(sample_text)
    assert sections is not None
    cover_rows = sections.cover_box_1_2.resolved_grid.rows
    assert cover_rows[3][0] == "500 East Pratt Street, Suite 1300, Baltimore, MD  21202"
    assert cover_rows[4][1] == "(410) 752-5900"
    assert cover_rows[8][0] == "500 East Pratt Street, Baltimore, MD  21202"
    assert sections.table_i is not None
    table_i_rows = sections.table_i.resolved_grid.rows
    assert table_i_rows[1][1] == "2/11/2013"
    assert table_i_rows[1][4] == "41,884"


def test_parse_ascii_form144_key_value() -> None:
    sample_text = """
1    (a) NAME OF ISSUER: Adams Natural Resources Fund, Inc.
     (b) IRS IDENT. NO.: 13-5506797
     (c) S.E.C. FILE NO.: 0000216851
2    (a) NAME OF PERSON FOR WHOSE ACCOUNT THE SECURITIES ARE TO BE SOLD:  Mark E. Stoeckle
     (b) RELATIONSHIP TO ISSUER:  CEO
3    (a) Common Stock
     (b) Convergex
     (c) Number of Shares or Other Units To Be Sold:  8,800
     (d) Aggregate Market Value:  $169,136
     (g) Name of Each Securities Exchange: NYSE
DATE OF NOTICE:  04/24/2017
SIGNATURE: /s/ Mark E. Stoeckle
"""
    sections = parse_ascii_form144(sample_text)
    assert sections is not None
    assert sections.cover_box_1_2 is not None
    cover_rows = sections.cover_box_1_2.resolved_grid.rows
    assert cover_rows[0][1] == "Adams Natural Resources Fund, Inc."
    assert cover_rows[5][1] == "Mark E. Stoeckle"

    assert sections.proposed_sale_box_3 is not None
    b3_rows = sections.proposed_sale_box_3.resolved_grid.rows
    assert len(b3_rows) >= 2
    assert b3_rows[1][2] == "8800"

    assert len(sections.signatures) == 1
    sig_rows = sections.signatures[0].resolved_grid.rows
    assert "04/24/2017" in sig_rows[0][0]
    assert "/s/ Mark E. Stoeckle" in sig_rows[0][1]


def test_parse_ascii_form144_labelled_list_box3() -> None:
    sample_text = """
1    (a) NAME OF ISSUER: South State Corporation
     (b) IRS IDENT. NO.: 57-0799315
2    (a) NAME OF PERSON FOR WHOSE ACCOUNT THE SECURITIES ARE TO BE SOLD:  Alton C. Phillips
     (b) RELATIONSHIP TO ISSUER:  Director
3(a) Title of Class of securities to be sold
Common Stock

3(b) Name and address of each broker through
whom the sec are to be offered/each market maker who is acquiring the securities
Wells Fargo Advisors, 200 Meeting St. Suite 302, Charleston, SC 29401

3(c) Number of share or other units to be sold
2,000

3(d)Aggregate Market Value
$160,000

3(e) Number of shares or other units outstanding
24,218,820

3(f) Approximate Date of Sale
11/10/2016

3(g) Name of each securities exchange
NASDAQ
"""
    sections = parse_ascii_form144(sample_text)
    assert sections is not None
    assert sections.proposed_sale_box_3 is not None
    b3_rows = sections.proposed_sale_box_3.resolved_grid.rows
    assert len(b3_rows) >= 2
    assert b3_rows[1][1] == (
        "Wells Fargo Advisors, 200 Meeting St. Suite 302, Charleston, SC 29401"
    )
    assert b3_rows[1][2] == "2000"
    assert b3_rows[1][3] == "160000"
    assert b3_rows[1][4] == "24218820"
    assert b3_rows[1][5] == "11/10/2016"
    assert b3_rows[1][6] == "NASDAQ"


def test_parse_ascii_form144_scaled_units() -> None:
    sample_text = """
1 (a) Name of issuer:
SPROUTS FARMERS MARKET, INC.
1 (b) IRS Ident. No.
32-0331600
2(a) Name of person for whose account the securities are to be sold
BRANDON LOMBARDI
3(a) Title of Class of securities to be sold
COMMON
3(c) Number of share or other units to be sold
25,834
3(d)Aggregate Market Value
$612,007.46
3(e) Number of shares or other units outstanding
133.1M
DATE OF NOTICE: 11/30/2017
SIGNATURE: /s/ Brandon Lombardi
"""
    sections = parse_ascii_form144(sample_text)
    assert sections is not None
    assert sections.cover_box_1_2 is not None
    assert (
        sections.cover_box_1_2.resolved_grid.rows[0][1]
        == "SPROUTS FARMERS MARKET, INC."
    )
    assert sections.cover_box_1_2.resolved_grid.rows[5][1] == "BRANDON LOMBARDI"
    assert sections.proposed_sale_box_3.resolved_grid.rows[1][2] == "25834"


def test_parse_ascii_form144_sgml_columns() -> None:
    sample_text = """
<TABLE>
<S>  <C>                                    <C>                 <C>
1(a) NAME OF ISSUER (Please type or print)  (b) IRS IDENT. NO.  (c) S.E.C. FILE NO.
     TREX Company, Inc.                         54-1910453          001-14649
2(a) NAME OF PERSON FOR WHOSE ACCOUNT       (b) IRS IDENT NO.   (c) RELATIONSHIP
     Connecticut General Life                   06-0303370          Shareholder
Common Stock   Cantor Fitzgerald & Co.   27,409   $1,224,840   14,127,822   06/05/2000   NYSE
June 5, 2000                                 By:  /s/ Stephen A. Osborn
              DATE OF NOTICE                              (SIGNATURE)
</TABLE>
"""
    sections = parse_ascii_form144(sample_text)
    assert sections is not None
    assert sections.cover_box_1_2.resolved_grid.rows[0][1] == "TREX Company, Inc."
    assert sections.cover_box_1_2.resolved_grid.rows[5][1] == "Connecticut General Life"
    assert sections.proposed_sale_box_3.resolved_grid.rows[1][2] == "27409"
    assert "Stephen A. Osborn" in sections.signatures[0].resolved_grid.rows[0][1]


def test_parse_ascii_form144_stacked_subtables_and_wrapped_headers() -> None:
    """Test multi-line wrapped cover headers and stacked Box 3 sub-tables."""
    sample_text = """
1(a) Name of Issuer: Triarc Companies, Inc.
1(d) Address of Issuer
            Street              City       State   Zip Code  (e) Telephone No.
      280 Park Avenue          New York    NY      10017      (212)451-3000
2(a) Name of Person for     (b) IRS       (c) Relationship
     Whose Account the          Ident.        to
     Securities are to          No.           Issuer
     Be Sold
     Gerald Tsai, Jr.           ###-##-####   Director
2(d) Address Street       City          State      Zip
 781 Fifth Avenue         New York       NY       10022
3(a) Title of      (b) Name and         SEC USE ONLY       (c) Number
    the Class of       Address of       Broker-Dealer          of Shares
Class A                Merril Lynch                              14,210
Common Stock           360 Hamilton Rd.
-----------------   ------------------- ------------------ ---------------------
3(d) Aggregate         (e) Number of         (f) Approximate       (g) Name of
     Market Value         Shares or             Date of Sale          Each
$358,802.50                20,275,678             07-11-01           NYSE
DATE OF NOTICE:  07/11/2001
SIGNATURE: /s/ Gerald Tsai, Jr.
"""
    sections = parse_ascii_form144(sample_text, reference_year=2001)
    assert sections is not None
    cover_rows = sections.cover_box_1_2.resolved_grid.rows
    assert cover_rows[0][1] == "Triarc Companies, Inc."
    assert cover_rows[5][1] == "Gerald Tsai, Jr."
    assert cover_rows[6][1] == "Director"
    b3_rows = sections.proposed_sale_box_3.resolved_grid.rows
    assert len(b3_rows) == 2
    assert "Common Stock" in b3_rows[1][0]
    assert b3_rows[1][1] == "Merril Lynch"
    assert b3_rows[1][2] == "14210"
    assert b3_rows[1][3] == "358802.50"
    assert b3_rows[1][4] == "20275678"
    assert b3_rows[1][5] == "07-11-01"
    assert b3_rows[1][6] == "NYSE"


def test_parse_ascii_form144_outer_box_pipes_and_david_luci() -> None:
    sample_text = """
|----------------------------------------------------------------------------------------------------------------------------------|
| 1(a) NAME OF ISSUER (Please type or print):                                      (b) IRS IDENT. NO.:      (c) S.E.C. FILE NO.:   |
|                                                                                                                                  |
|  Bioenvision, Inc.                                                                 13-4025875                 001-31787          |
|----------------------------------------------------------------------------------------------------------------------------------|
| 1(d) ADDRESS OF ISSUER ( STREET, CITY, STATE, ZIP CODE):                                         (e) TELEPHONE                   |
|345 Park Avenue, 41st Floor, New York, NY 10154                                 AREA CODE: 212   NUMBERS:      750-6700           |
|----------------------------------------------------------------------------------------------------------------------------------|
| 2(a) NAME OF PERSON FOR WHOSE ACCOUNT     (b) IRS IDENT.   (c) RELATIONSHIP TO    (d) ADDRESS (STREET, CITY, STATE, ZIP CODE):   |
| THE SECURITIES ARE TO BE SOLD:                NO.:             ISSUER:                                                           |
|                                                                                                                                  |
|    David P. Luci                                                 Officer          345 Park Avenue, 41st Floor, New York, NY 10154|
|----------------------------------------------------------------------------------------------------------------------------------|
|3(a) Title of the         (b) Broker           (c) Number of Shares    (d) Market Value   (e) Outstanding  (f) Date    (g) Exch   |
|----------------------------------------------------------------------------------------------------------------------------------|
| Common Stock             Smith Barney                        33,946       $317,395        28,882,319   December 15, 2004  Nasdaq |
|----------------------------------------------------------------------------------------------------------------------------------|
|                November 24, 2004                                               /s/ David P. Luci                                 |
|----------------------------------------------------------------------------------------------------------------------------------|
"""
    sections = parse_ascii_form144(sample_text, reference_year=2004)
    assert sections is not None
    cover_rows = sections.cover_box_1_2.resolved_grid.rows
    assert cover_rows[0][1] == "Bioenvision, Inc."
    assert cover_rows[1][1] == "13-4025875"
    assert cover_rows[1][3] == "001-31787"
    assert cover_rows[5][1] == "David P. Luci"
    assert cover_rows[6][1] == "Officer"
    b3_rows = sections.proposed_sale_box_3.resolved_grid.rows
    assert b3_rows[1][0] == "Common Stock"
    assert b3_rows[1][1] == "Smith Barney"
    assert b3_rows[1][2] == "33946"
    assert b3_rows[1][3] == "317395"
