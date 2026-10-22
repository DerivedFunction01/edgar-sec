from edgar_sec.engine.forms.ownership.issuer_parser import parse_issuer


def test_issuer_parser_extracts_conformed_tickers() -> None:
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
        issuer = parse_issuer(source)
        assert issuer.name == name
        assert issuer.trading_symbol == ticker


def test_issuer_parser_fallback_splits_common_delimiters() -> None:
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
        issuer = parse_issuer(source)
        assert issuer.name == name
        assert issuer.trading_symbol == ticker


def test_parse_issuer_combined_name_and_trading_symbol_line() -> None:
    issuer = parse_issuer("Name:   Example International Corp Trading Symbol:   EXMP")
    assert issuer.name == "Example International Corp"
    assert issuer.trading_symbol == "EXMP"


def test_issuer_parser_extracts_midline_group_symbols() -> None:
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
        issuer = parse_issuer(source)
        assert issuer.name == name
        assert issuer.trading_symbol == ticker


def test_issuer_parser_splits_glued_and_lowercase_symbols() -> None:
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
        issuer = parse_issuer(source)
        assert issuer.name == name
        assert issuer.trading_symbol == ticker


def test_issuer_parser_symbol_only_and_label_only_cells() -> None:
    issuer = parse_issuer("2. Issuer Name and Ticker or Trading Symbol\nLPTH")
    assert issuer.name is None
    assert issuer.trading_symbol == "LPTH"

    issuer = parse_issuer("2. Issuer Name and Ticker or Trading Symbol")
    assert issuer.name is None
    assert issuer.trading_symbol is None

    issuer = parse_issuer(
        "2. Issuer Name and Ticker or Trading Symbol\n"
        "Aberdeen Asia-Pacific Income Fund, Inc.\nSymbol: FAX"
    )
    assert issuer.name == "Aberdeen Asia-Pacific Income Fund, Inc."
    assert issuer.trading_symbol == "FAX"

    issuer = parse_issuer(
        "2. Issuer Name and Ticker or Trading Symbol\nNIKE, Inc.\nnke"
    )
    assert issuer.name == "NIKE, Inc."
    assert issuer.trading_symbol == "NKE"

    issuer = parse_issuer(
        "2. Issuer Name and Ticker or Trading Symbol\n"
        "First Interstate BancSystem, Inc. (no ticker or trading symbol)"
    )
    assert (
        issuer.name == "First Interstate BancSystem, Inc. (no ticker or trading symbol)"
    )
    assert issuer.trading_symbol is None


def test_parse_issuer_keeps_a_legal_form_name_with_a_parenthesized_symbol() -> None:
    issuer = parse_issuer(
        "2. Issuer Name and Ticker or Trading Symbol\nRF INDUSTRIES, LTD\n(RFIL)"
    )
    assert issuer.name == "RF INDUSTRIES, LTD"
    assert issuer.trading_symbol == "RFIL"


def test_parse_issuer_reads_brace_and_exchange_prefixed_groups() -> None:
    issuer = parse_issuer(
        "2. Issuer Name and Ticker or Trading Symbol\nCMS Energy Corporation {CMS}"
    )
    assert issuer.name == "CMS Energy Corporation"
    assert issuer.trading_symbol == "CMS"

    issuer = parse_issuer(
        "2. Issuer Name and Ticker or Trading Symbol\n"
        "Asbury Automotive Group, Inc. [NYSE: ABG]"
    )
    assert issuer.name == "Asbury Automotive Group, Inc."
    assert issuer.trading_symbol == "ABG"


def test_parse_issuer_ignores_a_grammatical_parenthetical() -> None:
    issuer = parse_issuer(
        "2. Issuer Name and Ticker or Trading Symbol\nPerson(s) to Issuer"
    )
    assert issuer.trading_symbol is None


def test_parse_issuer_rejects_na_as_a_symbol() -> None:
    issuer = parse_issuer(
        "2. Issuer Name and Ticker or Trading Symbol\nCroff Enterprises, Inc.\nN/A"
    )
    assert issuer.name == "Croff Enterprises, Inc."
    assert issuer.trading_symbol is None
