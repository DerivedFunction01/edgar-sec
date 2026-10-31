"""Tests for issuer header metadata extraction."""

from __future__ import annotations

from edgar_sec.engine.forms.beneficial_ownership.issuer import extract_issuer_metadata

_SAMPLE_HEADER = """
Name of Issuer: Stanley Furniture Company, Inc.
Title of Class of Securities: Common Stock, Par Value $0.02 Per Share
CUSIP Number: 854305208
Name of Person Authorized to Receive Notices and Communications: Justyn R. Putnam
Date of Event Which Requires Filing of This Statement: January 30, 2017
"""


def test_extract_issuer_metadata_parses_fields() -> None:
    meta = extract_issuer_metadata(_SAMPLE_HEADER)
    assert meta.issuer_name == "Stanley Furniture Company, Inc."
    assert meta.security_class == "Common Stock, Par Value $0.02 Per Share"
    assert meta.cusip == "854305208"
    assert meta.event_date == "January 30, 2017"
    assert meta.notice_contact == "Justyn R. Putnam"


def test_extract_issuer_metadata_handles_values_before_parenthesized_labels() -> None:
    meta = extract_issuer_metadata(
        "SCHEDULE 13D (Amendment No. 3) ENCORE ENERGY PARTNERS LP (Name of Issuer) "
        "COMMON UNITS (Title of Class of Securities) 29257A 106 (CUSIP Number) "
        "December 1, 2011 (Date of Event which Requires Filing of this Statement)"
    )

    assert meta.issuer_name == "ENCORE ENERGY PARTNERS LP"
    assert meta.security_class == "COMMON UNITS"
    assert meta.cusip == "29257A 106"
    assert meta.event_date == "December 1, 2011"


def test_extract_issuer_metadata_cleans_underscores_and_notice_block() -> None:
    meta = extract_issuer_metadata(
        """Dionex Corporation
(Name of Issuer)
Common Stock
(Title of Class of Securities)
_______254546104_________
(CUSIP Number)
Peter D. Goldstein
GAMCO Investors, Inc.
One Corporate Center
Rye, New York 10580-1435
(914) 921-5000
(Name, Address and Telephone Number of Person Authorized to Receive Notices and Communications)
______________________ February 2, 2011________________________
(Date of Event which Requires Filing of this Statement)"""
    )

    assert meta.cusip == "254546104"
    assert meta.event_date == "February 2, 2011"
    assert meta.notice_contact == "Peter D. Goldstein"
    assert meta.notice_phone == "(914) 921-5000"
    assert meta.notice_address.raw_text.startswith("GAMCO Investors, Inc.")
    assert meta.notice_address.street1 == "One Corporate Center"
    assert meta.notice_address.city == "Rye"
    assert meta.notice_address.state_or_country == "New York"


def test_extract_issuer_metadata_scopes_table_contact_after_last_cover_label() -> None:
    meta = extract_issuer_metadata(
        """UNITED STATES SECURITIES AND EXCHANGE COMMISSION
Washington, D.C. 20549
SCHEDULE 13D
Mawson Infrastructure Group Inc. (Name of Issuer)
Common Stock, par value $0.001 per share (Title of Class of Securities)
97751M207 (CUSIP Number)
<TABLE>
James Edward Manning
Level 5, 97 Pacific Highway, North Sydney C3 NSW 2060 Australia
+61 2 8624 6130
(Name, Address and Telephone Number of Person Authorized to Receive Notices and Communications)
</TABLE>"""
    )

    assert meta.issuer_name == "Mawson Infrastructure Group Inc."
    assert meta.cusip == "97751M207"
    assert meta.notice_contact == "James Edward Manning"
    assert meta.notice_phone == "+61 2 8624 6130"
    assert (
        meta.notice_address.raw_text
        == "Level 5, 97 Pacific Highway, North Sydney C3 NSW 2060 Australia"
    )


def test_extract_issuer_metadata_drops_missing_cusip_marker_and_page_residue() -> None:
    missing = extract_issuer_metadata("None. (CUSIP Number)")
    contaminated = extract_issuer_metadata("53071M500 SCHEDULE13D Page2 (CUSIP Number)")
    residue_only = extract_issuer_metadata("SCHEDULE 13D (CUSIP Number)")

    assert missing.cusip is None
    assert contaminated.cusip == "53071M500"
    assert residue_only.cusip is None


def test_extract_issuer_metadata_splits_inline_notice_contact_phone_and_address() -> (
    None
):
    meta = extract_issuer_metadata(
        """SenoRx, Inc. (Name of Issuer)
Shares of Common Stock (Title of Class of Securities)
81724W104 (CUSIP Number)
Paragon Associates and Paragon Associates II Joint Venture 500 Crescent Court, Suite 260 Dallas, Texas 75201 Tel. No.: (214) 871-3700
(Name, Address and Telephone Number of Person Authorized to Receive Notices and Communications)"""
    )

    assert (
        meta.notice_contact
        == "Paragon Associates and Paragon Associates II Joint Venture"
    )
    assert meta.notice_phone == "(214) 871-3700"
    assert meta.notice_address is not None
    assert meta.notice_address.street1 == "500 Crescent Court"
    assert meta.notice_address.street2 == "Suite 260"
    assert meta.notice_address.city == "Dallas"
    assert meta.notice_address.state_or_country == "Texas"
    assert meta.notice_address.zip_code == "75201"


def test_extract_issuer_metadata_prefers_attention_contact_and_excludes_copy_to() -> (
    None
):
    meta = extract_issuer_metadata(
        """New Skies Satellites Holdings Ltd. (Name of Issuer)
Common stock, par value $0.01 per share (Title of Class of Securities)
G64865101 (CUSIP Number)
SES Global S.A.
L-6815 Chateau de Betzdorf
Luxembourg
Attention: General Counsel
+352 710 725 575
Copy to:
David M. Wilf, Esq.
Gibson, Dunn & Crutcher LLP
200 Park Avenue
New York, New York 10016
(212) 351-4000
(Name, Address and Telephone Number of Person Authorized to Receive Notices and Communications)"""
    )

    assert meta.notice_contact == "General Counsel"
    assert meta.notice_phone == "+352 710 725 575"
    assert meta.notice_address is not None
    assert meta.notice_address.street1 == "L-6815 Chateau de Betzdorf"
    assert meta.notice_address.street2 == "Luxembourg"
    assert "Copy to" not in meta.notice_address.raw_text
    assert "David M. Wilf" not in meta.notice_address.raw_text


def test_extract_issuer_metadata_excludes_copy_to_from_primary_notice_address() -> None:
    meta = extract_issuer_metadata(
        """EasyLink Services International Corporation (Name of Issuer)
Class A Common Stock (Title of Class of Securities)
277858106 (CUSIP Number)
Nelson Obus
Wynnefield Capital, Inc.
450 Seventh Avenue, Suite 509
New York, New York 10123
Copy to:
Gersten Savage LLP
600 Lexington Avenue
New York, NY 10022
(212) 752-9700 Fax: (212) 980-5192
Attention: David E. Danovitch, Esq.
(Name, Address and Telephone Number of Person Authorized to Receive Notices and Communications)"""
    )

    assert meta.notice_contact == "David E. Danovitch, Esq."
    assert meta.notice_phone == "(212) 752-9700"
    assert meta.notice_address is not None
    assert meta.notice_address.street1 == "450 Seventh Avenue"
    assert meta.notice_address.street2 == "Suite 509"
    assert meta.notice_address.city == "New York"
    assert "Copy to" not in meta.notice_address.raw_text


def test_extract_issuer_metadata_skips_separator_lines_above_labels() -> None:
    meta = extract_issuer_metadata(
        """EDO Corporation
------------------------------------------------------
(Name of Issuer)

Common Stock
---------------------------------
(Title of Class of Securities)

28134710A
-----------------------
(Cusip Number)

December 31, 2003
_____________________________________
(Date of Event which requires filing of this Statement)"""
    )
    assert meta.issuer_name == "EDO Corporation"
    assert meta.security_class == "Common Stock"
    assert meta.cusip == "28134710A"
    assert meta.event_date == "December 31, 2003"


def test_issuer_extracts_isolated_header_date_without_explicit_label() -> None:
    meta = extract_issuer_metadata(
        """SCHEDULE 13G
JPMORGAN ETF
46641Q449
December 31, 2022
Check the appropriate box to designate the rule"""
    )
    assert meta.event_date == "December 31, 2022"
    assert meta.issuer_name == "JPMORGAN ETF"


def test_issuer_extracts_fmr_unlabelled_header() -> None:
    meta = extract_issuer_metadata(
        """SCHEDULE 13G

Amendment No. 9 Owens Illinois Incorporated common stock Cusip # 690768403

Cusip # 690768403
Item 1: Reporting Person - FMR Corp."""
    )
    assert meta.issuer_name == "Owens Illinois Incorporated"
    assert meta.cusip == "690768403"
    assert meta.security_class == "common stock"


def test_issuer_extracts_inline_formerly_known_as_label() -> None:
    meta = extract_issuer_metadata(
        "Genstar Therapeutics Corp. (Formerly known as Urogen Corp.) (Name of Issuer)\n"
        "Common Stock (Title of Class of Securities)\n"
        "917271 108 (CUSIP NUMBER)\n"
    )
    assert meta.issuer_name == "Genstar Therapeutics Corp."
    assert meta.cusip == "917271 108"
