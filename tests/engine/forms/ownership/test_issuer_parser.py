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
