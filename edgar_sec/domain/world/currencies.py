"""Currency records: the one declared standing for currency facts.

A record states a code, its names, its symbols, and whether a
symbol binds prefix or suffix; consumers derive their own sets.
The code set is attestation-gated (package README carries why).
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from types import MappingProxyType


@dataclass(frozen=True, slots=True)
class Currency:
    """One currency's declared facts."""

    code: str
    names: tuple[str, ...]
    symbols: tuple[str, ...]
    prefix: bool = True
    suffix: bool = False
    demonym: str | None = None
    country: str | None = None
    ambiguous_names: tuple[str, ...] = ()


_RECORDS: tuple[Currency, ...] = (
    Currency(
        code="USD",
        names=("dollar", "dollars", "usd", "u.s. dollar", "u.s. dollars"),
        symbols=("$",),
        demonym="american",
        country="US",
    ),
    Currency(
        code="EUR",
        names=("euro", "euros", "eur"),
        symbols=("€",),
    ),
    Currency(
        code="GBP",
        names=("pound", "pounds", "gbp", "sterling", "british pound"),
        symbols=("£",),
        demonym="british",
        country="GB",
        ambiguous_names=("pound", "pounds"),
    ),
    Currency(
        code="JPY",
        names=("yen", "jpy", "japanese yen"),
        symbols=("¥",),
        demonym="japanese",
        country="JP",
        ambiguous_names=("yen",),
    ),
    Currency(
        code="CAD",
        names=("canadian dollar", "canadian dollars", "cad"),
        symbols=("C$", "CAD$"),
        demonym="canadian",
        country="CA",
    ),
    Currency(
        code="AUD",
        names=("australian dollar", "australian dollars", "aud"),
        symbols=("A$", "AUD$"),
        demonym="australian",
        country="AU",
    ),
    Currency(
        code="CHF",
        names=("swiss franc", "swiss francs", "chf"),
        symbols=("CHF", "Fr."),
        demonym="swiss",
        country="CH",
    ),
    Currency(
        code="INR",
        names=("rupee", "rupees", "inr", "indian rupee"),
        symbols=("₹", "Rs.", "Rs"),
        demonym="indian",
        country="IN",
        ambiguous_names=("rupee", "rupees"),
    ),
    Currency(
        code="CNY",
        names=("yuan", "renminbi", "cny", "rmb", "chinese yuan"),
        symbols=("CN¥", "RMB"),
        demonym="chinese",
        country="CN",
        ambiguous_names=("yuan", "renminbi"),
    ),
    Currency(
        code="HKD",
        names=("hong kong dollar", "hong kong dollars", "hkd"),
        symbols=("HK$", "HKD$"),
        demonym="hong kong",
        country="HK",
    ),
    Currency(
        code="TWD",
        names=("new taiwan dollar", "taiwan dollar", "twd", "ntd"),
        symbols=("NT$", "NTD"),
        country="TW",
    ),
    Currency(
        code="KRW",
        names=("korean won", "krw", "south korean won"),
        symbols=("₩", "KRW"),
        demonym="korean",
        country="KR",
        ambiguous_names=("won",),
    ),
    Currency(
        code="SGD",
        names=("singapore dollar", "singapore dollars", "sgd"),
        symbols=("S$", "SGD$"),
        demonym="singaporean",
        country="SG",
    ),
    Currency(
        code="BRL",
        names=("real", "reais", "brazilian real", "brl"),
        symbols=("R$",),
        demonym="brazilian",
        country="BR",
    ),
    Currency(
        code="MXN",
        names=("mexican peso", "mexican pesos", "mxn"),
        symbols=("Mex$", "MXN$"),
        demonym="mexican",
        country="MX",
    ),
    Currency(
        code="SEK",
        names=("krona", "kronor", "swedish krona", "sek"),
        symbols=("kr", "SEK"),
        demonym="swedish",
        country="SE",
        ambiguous_names=("krona", "kronor"),
    ),
    Currency(
        code="DKK",
        names=("krone", "danish krone", "dkk"),
        symbols=("kr",),
        demonym="danish",
        country="DK",
        ambiguous_names=("krone",),
    ),
    Currency(
        code="ILS",
        names=("shekel", "shekels", "new israeli shekel", "ils", "nis"),
        symbols=("₪", "NIS"),
        demonym="israeli",
        country="IL",
        ambiguous_names=("shekel", "shekels"),
    ),
)

CURRENCIES: MappingProxyType[str, Currency] = MappingProxyType(
    {record.code: record for record in _RECORDS}
)

PREFIX_SYMBOLS: frozenset[str] = frozenset(
    symbol for record in _RECORDS if record.prefix for symbol in record.symbols
)
SUFFIX_SYMBOLS: frozenset[str] = frozenset(
    symbol for record in _RECORDS if record.suffix for symbol in record.symbols
)
ALL_CURRENCY_SYMBOLS: frozenset[str] = PREFIX_SYMBOLS | SUFFIX_SYMBOLS

SINGLE_CHARACTER_SYMBOLS: frozenset[str] = frozenset(
    symbol for symbol in ALL_CURRENCY_SYMBOLS if len(symbol) == 1
)
# The single-character symbols as a regex character-class body,
# homed here once; multi-character symbols ("kr", "Rs.") cannot
# sit in a single-character position and are excluded by shape.
SINGLE_CHARACTER_SYMBOL_CLASS: str = "".join(
    re.escape(symbol) for symbol in sorted(SINGLE_CHARACTER_SYMBOLS)
)


def currency(code: str) -> Currency:
    """The record for an ISO currency code; KeyError names the gap."""
    return CURRENCIES[code]


def currencies_for_symbol(symbol: str) -> tuple[str, ...]:
    """Codes whose records claim a symbol, in declaration order.
    A symbol with more than one owner is ambiguous by construction:
    "kr" is claimed by both SEK and DKK and resolves to neither alone.
    """
    return tuple(record.code for record in _RECORDS if symbol in record.symbols)


def currencies_for_name(name: str) -> tuple[str, ...]:
    """Codes whose records claim a name, in declaration order."""
    return tuple(record.code for record in _RECORDS if name in record.names)


__all__ = [
    "ALL_CURRENCY_SYMBOLS",
    "CURRENCIES",
    "PREFIX_SYMBOLS",
    "SINGLE_CHARACTER_SYMBOL_CLASS",
    "SINGLE_CHARACTER_SYMBOLS",
    "SUFFIX_SYMBOLS",
    "Currency",
    "currencies_for_name",
    "currencies_for_symbol",
    "currency",
]
