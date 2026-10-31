"""Legal-form suffixes, name stopwords, and entity-name tokenization.

Grammatical furniture carrying no identity: ``ACME HOLDINGS INC`` and ``ACME HOLDINGS
LLC`` are one registrant family.
"""

from __future__ import annotations

import re

from edgar_sec.domain.taxonomy.jurisdictions import strip_jurisdiction

# Entity-type words that do not distinguish one registrant family from another; non-US
# forms included because EDGAR carries foreign private issuers.
LEGAL_FORMS = frozenset(
    {
        "inc",
        "incorporated",
        "corp",
        "corporation",
        "co",
        "company",
        "ltd",
        "limited",
        "llc",
        "l.l.c.",
        "lp",
        "l.p.",
        "llp",
        "l.l.p.",
        "plc",
        "p.l.c.",
        "ag",
        "sa",
        "s.a.",
        "nv",
        "bv",
        "gmbh",
        "kgaa",
        "se",
        "srl",
        "pty",
        "pvt",
        "cia",
        "spa",
        "sl",
        "lda",
        "sociedad",
        "anonima",
        "holding",
        "holdings",
        "group",
        "grp",
        "trust",
        "fund",
        "bancorp",
        "bankshares",
    }
)

# Function words that carry no identity. "&" is included because EDGAR names use
# it in place of "and".
NAME_STOPWORDS = frozenset(
    {
        "the",
        "of",
        "or",
        "and",
        "&",
        "a",
        "an",
        "as",
        "is",
        "for",
        "by",
        "in",
        "on",
        "at",
        "to",
    }
)

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def entity_name_tokens(name: str) -> list[str]:
    """Return normalized lexical tokens without legal forms or stopwords.

    Single characters are dropped: they are formatting artifacts, not identity.
    """
    cleaned = strip_jurisdiction(name).lower()
    tokens = _TOKEN_RE.findall(cleaned)
    return [
        token
        for token in tokens
        if len(token) > 1 and token not in LEGAL_FORMS and token not in NAME_STOPWORDS
    ]


__all__ = ["LEGAL_FORMS", "NAME_STOPWORDS", "entity_name_tokens"]
