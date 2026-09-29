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

PREFIX_CURRENCY_SYMBOLS: frozenset[str] = frozenset(
    symbol
    for data in MAJOR_CURRENCIES.values()
    if data.get("prefix")
    for symbol in data.get("symbols", [])
)

SUFFIX_CURRENCY_SYMBOLS: frozenset[str] = frozenset(
    symbol
    for data in MAJOR_CURRENCIES.values()
    if data.get("suffix")
    for symbol in data.get("symbols", [])
)

ALL_CURRENCY_SYMBOLS: frozenset[str] = PREFIX_CURRENCY_SYMBOLS | SUFFIX_CURRENCY_SYMBOLS

__all__ = [
    "ALL_CURRENCY_SYMBOLS",
    "MAJOR_CURRENCIES",
    "PREFIX_CURRENCY_SYMBOLS",
    "SUFFIX_CURRENCY_SYMBOLS",
]
