"""Form 144 lexical evidence definitions, tokens, and veto phrases."""

from __future__ import annotations

from edgar_sec.foundation.text.evidence import EvidenceTier, LexicalEvidencePack

FORM144_HEADER_DECISIVE_PHRASES: tuple[str, ...] = (
    "notice of proposed sale of securities",
    "pursuant to rule 144",
    "form 144",
    "omb approval",
    "omb number",
)

FORM144_HEADER_LEXICAL_PACK = LexicalEvidencePack(
    name="form144_header",
    tiers=(
        EvidenceTier(
            name="header_decisive",
            priority=30,
            value=3,
            terms=FORM144_HEADER_DECISIVE_PHRASES,
            match_kind="ngram",
            min_distinct_hits=1,
        ),
    ),
)

FORM144_BOX_1_2_DECISIVE_PHRASES: tuple[str, ...] = (
    "name of issuer",
    "irs ident. no.",
    "s.e.c. file no.",
    "address of issuer",
    "name of person for whose account",
    "relationship to issuer",
)

FORM144_BOX_1_2_SUPPORT_TERMS: tuple[str, ...] = (
    "issuer",
    "officer",
    "director",
    "stockholder",
    "telephone",
    "street",
    "city",
    "state",
    "zip",
)

FORM144_BOX_1_2_LEXICAL_PACK = LexicalEvidencePack(
    name="form144_box_1_2",
    tiers=(
        EvidenceTier(
            name="box_1_2_decisive",
            priority=30,
            value=3,
            terms=FORM144_BOX_1_2_DECISIVE_PHRASES,
            match_kind="ngram",
            min_distinct_hits=1,
        ),
        EvidenceTier(
            name="box_1_2_support",
            priority=10,
            value=1,
            terms=FORM144_BOX_1_2_SUPPORT_TERMS,
            match_kind="unigram",
            support=True,
        ),
    ),
)

FORM144_BOX_3_DECISIVE_PHRASES: tuple[str, ...] = (
    "title of the class of securities to be sold",
    "name and address of each broker",
    "broker-dealer file number",
    "number of shares or other units to be sold",
    "aggregate market value",
    "number of shares or other units outstanding",
    "approximate date of sale",
    "name of each securities exchange",
)

FORM144_BOX_3_SUPPORT_TERMS: tuple[str, ...] = (
    "broker",
    "shares",
    "units",
    "market",
    "value",
    "outstanding",
    "exchange",
    "nasdaq",
    "nyse",
)

FORM144_BOX_3_LEXICAL_PACK = LexicalEvidencePack(
    name="form144_box_3",
    tiers=(
        EvidenceTier(
            name="box_3_decisive",
            priority=30,
            value=3,
            terms=FORM144_BOX_3_DECISIVE_PHRASES,
            match_kind="ngram",
            min_distinct_hits=1,
        ),
        EvidenceTier(
            name="box_3_support",
            priority=10,
            value=1,
            terms=FORM144_BOX_3_SUPPORT_TERMS,
            match_kind="unigram",
            support=True,
        ),
    ),
)

FORM144_TABLE_I_DECISIVE_PHRASES: tuple[str, ...] = (
    "table i - securities to be sold",
    "table i -- securities to be sold",
    "table i securities to be sold",
    "date you acquired",
    "nature of acquisition transaction",
    "name of person from whom acquired",
    "amount of securities acquired",
    "date of payment",
    "nature of payment",
)

FORM144_TABLE_I_SUPPORT_TERMS: tuple[str, ...] = (
    "acquired",
    "acquisition",
    "donor",
    "gift",
    "payment",
    "consideration",
)

FORM144_TABLE_I_LEXICAL_PACK = LexicalEvidencePack(
    name="form144_table_i",
    tiers=(
        EvidenceTier(
            name="table_i_decisive",
            priority=30,
            value=3,
            terms=FORM144_TABLE_I_DECISIVE_PHRASES,
            match_kind="ngram",
            min_distinct_hits=1,
        ),
        EvidenceTier(
            name="table_i_support",
            priority=10,
            value=1,
            terms=FORM144_TABLE_I_SUPPORT_TERMS,
            match_kind="unigram",
            support=True,
        ),
    ),
)

FORM144_TABLE_II_DECISIVE_PHRASES: tuple[str, ...] = (
    "table ii - securities sold during the past 3 months",
    "table ii -- securities sold during the past 3 months",
    "table ii securities sold",
    "securities sold during the past 3 months",
    "securities sold past 3 months",
    "name and address of seller",
    "title of securities sold",
    "date of sale",
    "amount of securities sold",
    "gross proceeds",
)

FORM144_TABLE_II_SUPPORT_TERMS: tuple[str, ...] = (
    "seller",
    "proceeds",
    "sold",
    "months",
)

FORM144_TABLE_II_LEXICAL_PACK = LexicalEvidencePack(
    name="form144_table_ii",
    tiers=(
        EvidenceTier(
            name="table_ii_decisive",
            priority=30,
            value=3,
            terms=FORM144_TABLE_II_DECISIVE_PHRASES,
            match_kind="ngram",
            min_distinct_hits=1,
        ),
        EvidenceTier(
            name="table_ii_support",
            priority=10,
            value=1,
            terms=FORM144_TABLE_II_SUPPORT_TERMS,
            match_kind="unigram",
            support=True,
        ),
    ),
)

FORM144_INSTRUCTION_VETO_PHRASES: tuple[str, ...] = (
    "potential persons who are to respond",
    "this form must be filed in electronic format",
    "filer should contact the issuer to obtain the s.e.c. file number",
    "sec 1147",
    "intentional misstatements or omission of facts",
    "see definition of person in paragraph",
    "see the definition of person in paragraph",
    "transmit for filing 3 copies",
    "instructions: 1.",
    "instructions: 2.",
    "instructions: 3.",
    "such persons relationship to the issuer",
    "such person's relationship to the issuer",
    "through whom the securities are intended to be sold",
    "if debt securities, give the face amount",
    "within 10 days prior to the filing of this notice",
    "most recent report or statement published by the issuer",
    "on which the securities are to be sold",
    "displays a currently valid omb",
    "notice shall be signed by the person for whose account",
    "full payment therefor was not made in cash",
    "full payment therefore was not made in cash",
    "nature of the consideration given",
    "executing a sale directly with a market maker",
)

__all__ = [
    "FORM144_BOX_1_2_LEXICAL_PACK",
    "FORM144_BOX_3_LEXICAL_PACK",
    "FORM144_HEADER_LEXICAL_PACK",
    "FORM144_INSTRUCTION_VETO_PHRASES",
    "FORM144_TABLE_I_LEXICAL_PACK",
    "FORM144_TABLE_II_LEXICAL_PACK",
]
