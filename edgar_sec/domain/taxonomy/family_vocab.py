"""Lexical tables and tuning constants for company-family normalization.

Every table here is immutable; a caller mutating one would make the clustering result
depend on call order rather than the input.
"""

from __future__ import annotations

from types import MappingProxyType

from edgar_sec.domain.taxonomy.jurisdictions import STATE_POSTAL_CODES

# Fixed so family ids are reproducible; changing it deliberately invalidates every
# derived family id.
SEED = "phase-02-company-family"

HEAD_TOKENS = 3
MIN_ALIAS_CHARS = 6
MIN_CLUSTER_ATTACH = 2
MAX_PARENT_TOKENS = 4
STRUCTURAL_THRESHOLD = 1

# Unambiguous abbreviations of security-depository vocabulary; the ambiguous ones live
# in CONTEXT_RULES, because expanding them blindly would corrupt unrelated names.
ABBR_MAP: MappingProxyType[str, str] = MappingProxyType(
    {
        "mort": "mortgage",
        "mrt": "mortgage",
        "mor": "mortgage",
        "mtg": "mortgage",
        "pas": "pass",
        "thr": "through",
        "thro": "through",
        "th": "through",
        "thru": "through",
        "cert": "certificate",
        "certs": "certificate",
        "crt": "certificate",
        "crts": "certificate",
        "cer": "certificate",
        "ce": "certificate",
        "ser": "series",
        "sec": "securities",
        "asst": "asset",
        "ast": "asset",
        "ass": "asset",
        "bck": "backed",
        "bkd": "backed",
        "nts": "notes",
        "ln": "loan",
        "eq": "equity",
        "hm": "home",
        "fd": "fund",
    }
)

# token -> (expansion, allowed previous, allowed next). An empty set means no constraint
# on that side; both neighbours are checked because "tr" is "trust" after a security
# type and "series" elsewhere.
CONTEXT_RULES: MappingProxyType[str, tuple[str, frozenset[str], frozenset[str]]] = (
    MappingProxyType(
        {
            "com": ("commercial", frozenset(), frozenset({"mortgage", "mor", "mrt"})),
            "comm": ("commercial", frozenset(), frozenset({"mortgage", "mor", "mrt"})),
            "ps": (
                "pass",
                frozenset({"mortgage", "mor", "mrt"}),
                frozenset({"through", "thr", "th", "thro"}),
            ),
            "bk": (
                "backed",
                frozenset({"asset", "asst", "as", "ast", "ln"}),
                frozenset({"certificate", "crt", "cer"}),
            ),
            "as": (
                "asset",
                frozenset({"ln", "loan"}),
                frozenset({"bk", "bck", "bkd", "backed"}),
            ),
            "tr": (
                "trust",
                frozenset(
                    {
                        "securities",
                        "sec",
                        "ln",
                        "eq",
                        "bck",
                        "bk",
                        "mortgage",
                        "d",
                        "series",
                    }
                ),
                frozenset(),
            ),
            "ct": (
                "certificate",
                frozenset({"through", "thr", "th", "pass", "pas", "ps"}),
                frozenset(),
            ),
            "sr": (
                "series",
                frozenset({"certificate", "crt", "cert", "ce"}),
                frozenset(),
            ),
            "se": (
                "series",
                frozenset({"certificate", "ce", "cert", "crt"}),
                frozenset(),
            ),
            "srs": (
                "series",
                frozenset({"certificate", "certs", "crt", "through", "thr"}),
                frozenset(),
            ),
        }
    )
)

# Singular forms, applied after abbreviation expansion. "securities" and
# "equities" are the two that matter most: the same trust appears as both.
PLURAL_MAP: MappingProxyType[str, str] = MappingProxyType(
    {
        "securities": "security",
        "receivables": "receivable",
        "certificates": "certificate",
        "loans": "loan",
        "funds": "fund",
        "assets": "asset",
        "notes": "note",
        "investors": "investor",
        "holdings": "holding",
        "partners": "partner",
        "properties": "property",
        "investments": "investment",
        "resources": "resource",
        "enterprises": "enterprise",
        "products": "product",
        "mortgages": "mortgage",
        "equities": "equity",
    }
)

# Roman numerals, so "SERIES IV" and "SERIES D" collapse to the same token.
ROMAN = frozenset(
    {
        "i",
        "ii",
        "iii",
        "iv",
        "v",
        "vi",
        "vii",
        "viii",
        "ix",
        "x",
        "xi",
        "xii",
        "xiii",
        "xiv",
        "xv",
        "xvi",
        "xvii",
        "xviii",
        "xix",
        "xx",
    }
)

# Single letters standing in for a varying part of a name, excluded from family keys
# so a series letter never splits one family into many.
PLACEHOLDER = frozenset({"D", "S", "R"})

STATE_CODES: tuple[str, ...] = tuple(sorted(c.lower() for c in STATE_POSTAL_CODES))

__all__ = [
    "ABBR_MAP",
    "CONTEXT_RULES",
    "HEAD_TOKENS",
    "MAX_PARENT_TOKENS",
    "MIN_ALIAS_CHARS",
    "MIN_CLUSTER_ATTACH",
    "PLACEHOLDER",
    "PLURAL_MAP",
    "ROMAN",
    "SEED",
    "STATE_CODES",
    "STRUCTURAL_THRESHOLD",
]
