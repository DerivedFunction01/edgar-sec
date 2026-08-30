"""Major currency symbols and metadata for financial table extraction."""

from __future__ import annotations

from typing import Any

MAJOR_CURRENCIES: dict[str, dict[str, Any]] = {
    "USD": {
        "names": ["dollar", "dollars", "usd", "u.s. dollar", "u.s. dollars"],
        "symbols": ["$"],
        "prefix": True,
        "suffix": False,
    },
    "EUR": {
        "names": ["euro", "euros", "eur"],
        "symbols": ["€"],
        "prefix": True,
        "suffix": False,
    },
    "GBP": {
        "names": ["pound", "pounds", "gbp", "sterling", "british pound"],
        "symbols": ["£"],
        "prefix": True,
        "suffix": False,
    },
    "JPY": {
        "names": ["yen", "jpy", "japanese yen"],
        "symbols": ["¥"],
        "prefix": True,
        "suffix": False,
    },
    "CAD": {
        "names": ["canadian dollar", "canadian dollars", "cad"],
        "symbols": ["C$", "CAD$"],
        "prefix": True,
        "suffix": False,
    },
    "AUD": {
        "names": ["australian dollar", "australian dollars", "aud"],
        "symbols": ["A$", "AUD$"],
        "prefix": True,
        "suffix": False,
    },
    "CHF": {
        "names": ["swiss franc", "swiss francs", "chf"],
        "symbols": ["CHF", "Fr."],
        "prefix": True,
        "suffix": False,
    },
    "INR": {
        "names": ["rupee", "rupees", "inr", "indian rupee"],
        "symbols": ["₹", "Rs.", "Rs"],
        "prefix": True,
        "suffix": False,
    },
    "CNY": {
        "names": ["yuan", "renminbi", "cny", "rmb", "chinese yuan"],
        "symbols": ["CN¥", "RMB"],
        "prefix": True,
        "suffix": False,
    },
}

PREFIX_SYMBOLS: set[str] = set()
SUFFIX_SYMBOLS: set[str] = set()

for _data in MAJOR_CURRENCIES.values():
    _syms = _data.get("symbols", [])
    if _data.get("prefix"):
        PREFIX_SYMBOLS.update(_syms)
    if _data.get("suffix"):
        SUFFIX_SYMBOLS.update(_syms)

__all__ = [
    "MAJOR_CURRENCIES",
    "PREFIX_SYMBOLS",
    "SUFFIX_SYMBOLS",
]
