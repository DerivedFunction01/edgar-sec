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

ALL_CURRENCY_SYMBOLS: frozenset[str] = frozenset(PREFIX_SYMBOLS | SUFFIX_SYMBOLS)


def detect_currency_affix(
    grid_or_cells: list[list[str]] | list[str] | str,
) -> tuple[str | None, bool]:
    """Detect dominant currency symbol and whether it acts as a prefix or suffix.

    Supports domestic (USD prefix: ``$376.90``) and international/20-F formats
    (EUR suffix: ``376.90 €``, CHF, GBP, etc.).

    Args:
        grid_or_cells: 2D table grid, 1D list of cell strings, or a text string.

    Returns:
        (symbol, is_suffix) tuple. Returns (None, False) if no currency is found.
    """
    sorted_symbols = sorted(ALL_CURRENCY_SYMBOLS, key=len, reverse=True)

    # 1. Inspect 2D grid structure for position-aware column detection
    if (
        isinstance(grid_or_cells, list)
        and grid_or_cells
        and isinstance(grid_or_cells[0], list)
    ):
        for row in grid_or_cells:
            for idx, cell in enumerate(row):
                stripped = cell.strip()
                if stripped in ALL_CURRENCY_SYMBOLS:
                    # Check if preceding cell was populated (suffix column)
                    has_preceding = any(row[p].strip() for p in range(idx))
                    has_following = any(
                        row[f].strip() for f in range(idx + 1, len(row))
                    )
                    is_suffix = has_preceding and not has_following
                    return stripped, is_suffix

                for sym in sorted_symbols:
                    if stripped.endswith(sym):
                        return sym, True
                    if stripped.startswith(sym):
                        return sym, False

    # 2. Fallback for 1D cell list or single string
    cells = (
        [grid_or_cells]
        if isinstance(grid_or_cells, str)
        else [c for c in grid_or_cells if c.strip()]
    )
    for cell in cells:
        stripped = cell.strip()
        if stripped in ALL_CURRENCY_SYMBOLS:
            return stripped, stripped in SUFFIX_SYMBOLS
        for sym in sorted_symbols:
            if stripped.endswith(sym):
                return sym, True
            if stripped.startswith(sym):
                return sym, False

    return None, False


def format_currency(
    value: str,
    symbol: str | None,
    *,
    is_suffix: bool = False,
) -> str:
    """Apply currency symbol as prefix or suffix, avoiding duplicate symbols."""
    if not symbol or not value:
        return value
    if any(s in value for s in ALL_CURRENCY_SYMBOLS):
        return value
    return f"{value} {symbol}" if is_suffix else f"{symbol}{value}"


__all__ = [
    "ALL_CURRENCY_SYMBOLS",
    "MAJOR_CURRENCIES",
    "PREFIX_SYMBOLS",
    "SUFFIX_SYMBOLS",
    "detect_currency_affix",
    "format_currency",
]
