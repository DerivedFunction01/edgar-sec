"""Phrase sequence rules for Form 144 text healing."""

from __future__ import annotations

from edgar_sec.foundation.text.healing import PhraseSequenceRule

FORM144_PHRASE_RULES: tuple[PhraseSequenceRule, ...] = (
    PhraseSequenceRule(
        name="box_1a_name_of_issuer",
        tokens=[["1", "1a"], "a", "name", "of", "issuer"],
        anchor=["1", "1a", "name", "issuer"],
    ),
    PhraseSequenceRule(
        name="box_1b_irs_ident_no",
        tokens=[["1", "1b", "b"], ["b", "irs"], "irs", "ident", "no"],
        anchor=["irs", "ident"],
    ),
    PhraseSequenceRule(
        name="box_1c_sec_file_no",
        tokens=[["1", "1c", "c"], ["c", "s", "sec"], "sec", "file", "no"],
        anchor=["file"],
    ),
    PhraseSequenceRule(
        name="box_2a_name_of_person",
        tokens=[
            ["2", "2a"],
            "a",
            "name",
            "of",
            "person",
            "for",
            "whose",
            "account",
            "the",
            "securities",
            "are",
            "to",
            "be",
            "sold",
        ],
        anchor=["2", "2a", "person", "whose", "account", "sold"],
    ),
    PhraseSequenceRule(
        name="box_2c_relationship",
        tokens=[["c", "relationship"], "to", "issuer"],
        anchor=["relationship", "issuer"],
    ),
    PhraseSequenceRule(
        name="box_3a_title_of_class",
        tokens=[
            ["3", "3a"],
            "a",
            "title",
            "of",
            ["the", "each"],
            "class",
            "of",
            "securities",
            "to",
            "be",
            "sold",
        ],
        anchor=["3", "3a", "title", "class"],
    ),
    PhraseSequenceRule(
        name="box_3b_name_address_broker",
        tokens=[["3", "3b"], "b", "name", "and", "address", "of", "each", "broker"],
        anchor=["3", "3b", "broker"],
    ),
    PhraseSequenceRule(
        name="box_3c_number_of_shares",
        tokens=[
            ["3", "3c"],
            "c",
            "number",
            "of",
            ["shares", "units"],
            "or",
            "other",
            ["units", "shares"],
            "to",
            "be",
            "sold",
        ],
        anchor=["3", "3c", "number", "units", "shares"],
    ),
    PhraseSequenceRule(
        name="box_3d_market_value",
        tokens=[["3", "3d"], "d", "aggregate", "market", "value"],
        anchor=["3", "3d", "aggregate", "market", "value"],
    ),
    PhraseSequenceRule(
        name="box_3e_outstanding",
        tokens=[
            ["3", "3e"],
            "e",
            "number",
            "of",
            ["shares", "units"],
            "or",
            "other",
            ["units", "shares"],
            "outstanding",
        ],
        anchor=["3", "3e", "outstanding"],
    ),
    PhraseSequenceRule(
        name="box_3f_sale_date",
        tokens=[["3", "3f"], "f", "approximate", "date", "of", "sale"],
        anchor=["3", "3f", "approximate", "sale"],
    ),
    PhraseSequenceRule(
        name="box_3g_exchange",
        tokens=[["3", "3g"], "g", "name", "of", "each", "securities", "exchange"],
        anchor=["3", "3g", "exchange"],
    ),
)

__all__ = ["FORM144_PHRASE_RULES"]
