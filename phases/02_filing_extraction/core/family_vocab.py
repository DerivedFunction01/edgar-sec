"""Lexical tables, abbreviations, contextual rules, and legal forms for entity normalization."""

from __future__ import annotations

from defs.entities import LEGAL_FORMS, STATE_POSTAL_CODES

SEED = "phase-02-company-family"
HEAD_TOKENS = 3
MIN_ALIAS_CHARS = 6
MIN_CLUSTER_ATTACH = 2
MAX_PARENT_TOKENS = 4
STRUCTURAL_THRESHOLD = 1

ABBR_MAP: dict[str, str] = {
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

CONTEXT_RULES: dict[str, tuple[str, set[str], set[str]]] = {
    "com": ("commercial", set(), {"mortgage", "mor", "mrt"}),
    "comm": ("commercial", set(), {"mortgage", "mor", "mrt"}),
    "ps": ("pass", {"mortgage", "mor", "mrt"}, {"through", "thr", "th", "thro"}),
    "bk": (
        "backed",
        {"asset", "asst", "as", "ast", "ln"},
        {"certificate", "crt", "cer"},
    ),
    "as": ("asset", {"ln", "loan"}, {"bk", "bck", "bkd", "backed"}),
    "tr": (
        "trust",
        {"securities", "sec", "ln", "eq", "bck", "bk", "mortgage", "D", "series"},
        set(),
    ),
    "ct": ("certificate", {"through", "thr", "th", "pass", "pas", "ps"}, set()),
    "sr": ("series", {"certificate", "crt", "cert", "ce"}, set()),
    "se": ("series", {"certificate", "ce", "cert", "crt"}, set()),
    "srs": ("series", {"certificate", "certs", "crt", "through", "thr"}, set()),
}

PLURAL_MAP: dict[str, str] = {
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

ROMAN: set[str] = {
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

PLACEHOLDER: set[str] = {"D", "S", "R"}

STATE_CODES: list[str] = sorted(code.lower() for code in STATE_POSTAL_CODES)

__all__ = [
    "ABBR_MAP",
    "CONTEXT_RULES",
    "HEAD_TOKENS",
    "LEGAL_FORMS",
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
