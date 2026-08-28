"""Normalization of entity identity, listings, former names, and addresses."""

from __future__ import annotations

import re
from typing import Any

from .helpers import (
    add_anomaly,
    canonical_json,
    to_bool,
)

PROFILE_KEYS = {
    "cik",
    "entityType",
    "sic",
    "sicDescription",
    "ownerOrg",
    "insiderTransactionForOwnerExists",
    "insiderTransactionForIssuerExists",
    "name",
    "tickers",
    "exchanges",
    "ein",
    "lei",
    "description",
    "website",
    "investorWebsite",
    "category",
    "fiscalYearEnd",
    "stateOfIncorporation",
    "stateOfIncorporationDescription",
    "phone",
    "flags",
    "formerNames",
    "addresses",
    "filings",
}

ADDRESS_KEYS = [
    "street1",
    "street2",
    "city",
    "stateOrCountry",
    "zipCode",
    "stateOrCountryDescription",
    "country",
    "countryCode",
    "foreignStateTerritory",
    "isForeignLocation",
]

_CAMEL_BOUNDARY_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def address_field(raw_key: str) -> str:
    """Map an SEC address key to its canonical snake_case field name."""
    return _CAMEL_BOUNDARY_RE.sub("_", raw_key).lower()


def zip_listings(tickers: Any, exchanges: Any, anomalies: list[dict]) -> list[dict]:
    """Zip tickers and exchanges by index, preserving order and duplicate
    exchange values. Length mismatches keep the longer side with a null."""
    tickers = tickers if isinstance(tickers, list) else []
    exchanges = exchanges if isinstance(exchanges, list) else []
    if len(tickers) != len(exchanges):
        add_anomaly(
            anomalies,
            "listings_length_mismatch",
            f"tickers={len(tickers)} exchanges={len(exchanges)}; missing side padded with null",
            "tickers/exchanges",
        )
    listings = []
    for index in range(max(len(tickers), len(exchanges))):
        ticker = tickers[index] if index < len(tickers) else None
        exchange = exchanges[index] if index < len(exchanges) else None
        listings.append({"ticker": ticker, "exchange": exchange})
    return listings


def normalize_address(value: Any, anomalies: list[dict], source: str) -> dict | None:
    """Normalize one address object. A missing key yields None; an empty
    object yields an all-null struct so 'not supplied' stays distinct from
    'supplied but empty'. ``isForeignLocation`` is coerced with ``to_bool``
    like the filing-history booleans."""
    if value is None:
        return None
    if not isinstance(value, dict):
        add_anomaly(
            anomalies,
            "address_not_object",
            f"unexpected type {type(value).__name__}",
            source,
        )
        return None
    unknown = [key for key in value if key not in ADDRESS_KEYS]
    if unknown:
        add_anomaly(
            anomalies,
            "unknown_address_keys",
            canonical_json(sorted(unknown)),
            source,
        )
    out = {}
    for raw_key in ADDRESS_KEYS:
        out[address_field(raw_key)] = value.get(raw_key)
    out["is_foreign_location"] = to_bool(out["is_foreign_location"])
    return out


def normalize_former_names(value: Any, anomalies: list[dict]) -> list[dict]:
    """Normalize formerNames. SEC uses arrays of [name, from, to]; objects
    are accepted defensively. Unknown shapes are flagged, not dropped."""
    if value is None:
        return []
    if not isinstance(value, list):
        add_anomaly(
            anomalies, "former_names_not_list", type(value).__name__, "formerNames"
        )
        return []
    out = []
    for index, entry in enumerate(value):
        if isinstance(entry, (list, tuple)):
            parts = list(entry) + [None] * (3 - len(entry))
            out.append({"name": parts[0], "from_date": parts[1], "to_date": parts[2]})
        elif isinstance(entry, dict):
            out.append(
                {
                    "name": entry.get("name"),
                    "from_date": entry.get("from"),
                    "to_date": entry.get("to"),
                }
            )
        else:
            add_anomaly(
                anomalies,
                "former_names_entry",
                canonical_json(entry)[:200],
                f"formerNames[{index}]",
            )
            out.append({"name": entry, "from_date": None, "to_date": None})
    return out


__all__ = [
    "ADDRESS_KEYS",
    "PROFILE_KEYS",
    "address_field",
    "normalize_address",
    "normalize_former_names",
    "zip_listings",
]
