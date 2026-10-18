"""Unit tests for Form 144 ASCII state machine parser."""

from pathlib import Path

from edgar_sec.engine.forms.form144.ascii_parser import parse_ascii_form144


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
    assert cover_rows[2][1] == "Mark E. Stoeckle"

    assert sections.proposed_sale_box_3 is not None
    b3_rows = sections.proposed_sale_box_3.resolved_grid.rows
    assert len(b3_rows) >= 2
    assert b3_rows[1][2] == "8800"

    assert len(sections.signatures) == 1
    sig_rows = sections.signatures[0].resolved_grid.rows
    assert "04/24/2017" in sig_rows[0][0]
    assert "/s/ Mark E. Stoeckle" in sig_rows[0][1]


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
    assert sections.cover_box_1_2.resolved_grid.rows[2][1] == "BRANDON LOMBARDI"
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
    assert sections.cover_box_1_2.resolved_grid.rows[2][1] == "Connecticut General Life"
    assert sections.proposed_sale_box_3.resolved_grid.rows[1][2] == "27409"
    assert "Stephen A. Osborn" in sections.signatures[0].resolved_grid.rows[0][1]
