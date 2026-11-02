from edgar_sec.engine.forms.cover.registrant import (
    is_separator_line,
    next_content_line,
    parse_registrant_identity,
    previous_content_line,
)


def test_registrant_extracts_conformed_tickers() -> None:
    cases = (
        (
            "Issuer Name: Macrovision Corporation (Nasdaq: MVSN)",
            "Macrovision Corporation",
            "MVSN",
        ),
        (
            '2. Issuer Name and Ticker: Dendrite International Inc ("DRTE")',
            "Dendrite International Inc",
            "DRTE",
        ),
        ("Issuer Name: Emerson Electric Co. - EMR", "Emerson Electric Co.", "EMR"),
        (
            "2. Issuer Name and Ticker or Trading Symbol\nSizeler Property Investors, Inc.\nSIZ",
            "Sizeler Property Investors, Inc.",
            "SIZ",
        ),
        (
            "2. Issuer Name and Ticker or Trading Symbol\nThe Neiman Marcus Group, Inc.\n(NMG.A and NMG.B)",
            "The Neiman Marcus Group, Inc.",
            "NMG.A",
        ),
    )

    for source, name, ticker in cases:
        identity = parse_registrant_identity(source)
        assert identity.name == name
        assert identity.trading_symbol == ticker


def test_registrant_fallback_splits_common_delimiters() -> None:
    cases = (
        (
            "2. Issuer Name and Ticker\nFarmers National Banc Corp./FMNB.OB",
            "Farmers National Banc Corp.",
            "FMNB.OB",
        ),
        (
            "2. Issuer Name and Ticker\nOil States International, Inc. - OIS",
            "Oil States International, Inc.",
            "OIS",
        ),
        ("2. Issuer Name and Ticker\nAcme Corp and ACM", "Acme Corp", "ACM"),
    )

    for source, name, ticker in cases:
        identity = parse_registrant_identity(source)
        assert identity.name == name
        assert identity.trading_symbol == ticker


def test_parse_registrant_combined_name_and_trading_symbol_line() -> None:
    identity = parse_registrant_identity(
        "Name:   Example International Corp Trading Symbol:   EXMP"
    )
    assert identity.name == "Example International Corp"
    assert identity.trading_symbol == "EXMP"


def test_registrant_extracts_midline_group_symbols() -> None:
    cases = (
        (
            "2. Issuer Name and Ticker or Trading Symbol\n"
            "Latin American Casinos, Inc. (LACI) (Nasdaq National Market)",
            "Latin American Casinos, Inc.",
            "LACI",
        ),
        (
            "2. Issuer Name and Ticker or Trading Symbol\n"
            'Numerical Technologies, Inc. (NMTC) (the "Company")',
            "Numerical Technologies, Inc.",
            "NMTC",
        ),
        (
            "2. Issuer Name and Ticker or Trading Symbol\n"
            'Delcath Systems, Inc. ("DCTH" (1) "DCT" (2))',
            "Delcath Systems, Inc.",
            "DCTH",
        ),
        (
            "2. Issuer Name and Ticker or Trading Symbol\n"
            "Putnam High Income Convertible and Bond Fund [PCF]",
            "Putnam High Income Convertible and Bond Fund",
            "PCF",
        ),
        (
            "2. Issuer Name and Ticker or Trading Symbol\n"
            'Cerprobe Corporation ("CRPB")',
            "Cerprobe Corporation",
            "CRPB",
        ),
    )

    for source, name, ticker in cases:
        identity = parse_registrant_identity(source)
        assert identity.name == name
        assert identity.trading_symbol == ticker


def test_registrant_splits_glued_and_lowercase_symbols() -> None:
    cases = (
        (
            "2. Issuer Name and Ticker or Trading Symbol\nWinmark Corporation wina",
            "Winmark Corporation",
            "WINA",
        ),
        (
            "2. Issuer Name and Ticker or Trading Symbol\nPizza Inn, Inc. pzzi",
            "Pizza Inn, Inc.",
            "PZZI",
        ),
        (
            "2. Issuer Name and Ticker or Trading Symbol\nLimited Brands, Inc. LTD",
            "Limited Brands, Inc.",
            "LTD",
        ),
        (
            "2. Issuer Name and Ticker or Trading Symbol\nAmeriServ Financial, Inc.\tASRV",
            "AmeriServ Financial, Inc.",
            "ASRV",
        ),
        (
            "2. Issuer Name and Ticker or Trading Symbol\nFirst Merchants Corporation-FRME",
            "First Merchants Corporation",
            "FRME",
        ),
        (
            "2. Issuer Name and Ticker or Trading Symbol\ncsbb.ob CSB Bancorp, Inc.",
            "CSB Bancorp, Inc.",
            "CSBB.OB",
        ),
    )

    for source, name, ticker in cases:
        identity = parse_registrant_identity(source)
        assert identity.name == name
        assert identity.trading_symbol == ticker


def test_registrant_symbol_only_and_label_only_cells() -> None:
    identity = parse_registrant_identity(
        "2. Issuer Name and Ticker or Trading Symbol\nLPTH"
    )
    assert identity.name is None
    assert identity.trading_symbol == "LPTH"

    identity = parse_registrant_identity("2. Issuer Name and Ticker or Trading Symbol")
    assert identity.name is None
    assert identity.trading_symbol is None

    identity = parse_registrant_identity(
        "2. Issuer Name and Ticker or Trading Symbol\n"
        "Aberdeen Asia-Pacific Income Fund, Inc.\nSymbol: FAX"
    )
    assert identity.name == "Aberdeen Asia-Pacific Income Fund, Inc."
    assert identity.trading_symbol == "FAX"

    identity = parse_registrant_identity(
        "2. Issuer Name and Ticker or Trading Symbol\nNIKE, Inc.\nnke"
    )
    assert identity.name == "NIKE, Inc."
    assert identity.trading_symbol == "NKE"

    identity = parse_registrant_identity(
        "2. Issuer Name and Ticker or Trading Symbol\n"
        "First Interstate BancSystem, Inc. (no ticker or trading symbol)"
    )
    assert (
        identity.name
        == "First Interstate BancSystem, Inc. (no ticker or trading symbol)"
    )
    assert identity.trading_symbol is None


def test_parse_registrant_keeps_a_legal_form_name_with_a_parenthesized_symbol() -> None:
    identity = parse_registrant_identity(
        "2. Issuer Name and Ticker or Trading Symbol\nRF INDUSTRIES, LTD\n(RFIL)"
    )
    assert identity.name == "RF INDUSTRIES, LTD"
    assert identity.trading_symbol == "RFIL"


def test_parse_registrant_reads_brace_and_exchange_prefixed_groups() -> None:
    identity = parse_registrant_identity(
        "2. Issuer Name and Ticker or Trading Symbol\nCMS Energy Corporation {CMS}"
    )
    assert identity.name == "CMS Energy Corporation"
    assert identity.trading_symbol == "CMS"

    identity = parse_registrant_identity(
        "2. Issuer Name and Ticker or Trading Symbol\n"
        "Asbury Automotive Group, Inc. [NYSE: ABG]"
    )
    assert identity.name == "Asbury Automotive Group, Inc."
    assert identity.trading_symbol == "ABG"


def test_parse_registrant_ignores_a_grammatical_parenthetical() -> None:
    identity = parse_registrant_identity(
        "2. Issuer Name and Ticker or Trading Symbol\nPerson(s) to Issuer"
    )
    assert identity.trading_symbol is None


def test_parse_registrant_rejects_na_as_a_symbol() -> None:
    identity = parse_registrant_identity(
        "2. Issuer Name and Ticker or Trading Symbol\nCroff Enterprises, Inc.\nN/A"
    )
    assert identity.name == "Croff Enterprises, Inc."
    assert identity.trading_symbol is None


def test_content_line_walks_skip_blanks_and_separators() -> None:
    lines = ["ACME INC.", "", "-----------", "(Exact name of registrant)"]
    assert is_separator_line("-----------") is True
    assert is_separator_line("") is True
    assert is_separator_line("ACME INC.") is False
    assert previous_content_line(lines, 3) == (0, "ACME INC.")
    assert next_content_line(lines, 0) == (3, "(Exact name of registrant)")
    assert previous_content_line(lines, 0) is None
    assert next_content_line(lines, 3) is None
