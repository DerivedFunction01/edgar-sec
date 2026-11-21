"""Legal-form suffixes, name stopwords, and entity-name tokenization.

Grammatical furniture carrying no identity: ``ACME HOLDINGS INC`` and ``ACME HOLDINGS
LLC`` are one registrant family.
"""

from __future__ import annotations

import re

from edgar_sec.domain.taxonomy.family_vocab import (
    CORPORATE_DESIGNATORS,
    IDENTITY_NOUNS,
)
from edgar_sec.domain.taxonomy.jurisdictions import strip_jurisdiction

# Entity-type words that do not distinguish one registrant family from another; non-US
# forms included because EDGAR carries foreign private issuers.
LEGAL_FORMS = frozenset(
    {
        *CORPORATE_DESIGNATORS,
        *IDENTITY_NOUNS,
        "company",
        "cia",
        "etf",
        "grp",
        "holdings",
        "l.l.c.",
        "l.l.p.",
        "l.p.",
        "p.l.c.",
        "s.a.",
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


def has_legal_form(name: str) -> bool:
    """Return whether name contains any legal-form token."""
    cleaned = strip_jurisdiction(name).lower()
    return any(token in LEGAL_FORMS for token in _TOKEN_RE.findall(cleaned))


__all__ = ["LEGAL_FORMS", "NAME_STOPWORDS", "entity_name_tokens", "has_legal_form"]
