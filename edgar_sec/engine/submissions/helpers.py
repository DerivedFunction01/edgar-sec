"""Coercion, alias resolution, and anomaly recording for submissions payloads.

SEC submissions JSON is loosely typed and varies across eras. Every coercion
here is total: invalid input yields ``None`` or an empty collection and is
reported through an anomaly rather than raised, so one malformed field can
never discard an otherwise valid filing record.
"""

from __future__ import annotations

import re
from typing import Any

from edgar_sec.domain.sec_urls import (
    archives_url,
)
from edgar_sec.foundation.serialization import canonical_json

ACCESSION_RE = re.compile(r"^\d{10}-\d{2}-\d{6}$")

__all__ = [
    "ACCESSION_RE",
    "accession_normalized",
    "add_anomaly",
    "build_archive_url",
    "canonical_json",
    "normalize_cik_padded",
    "normalize_items",
    "resolve_alias",
    "to_bool",
    "to_int",
]


def add_anomaly(
    anomalies: list[dict], code: str, detail: str, source: str = ""
) -> None:
    """Append one anomaly record in the canonical ``{code, detail, source}`` shape."""
    anomalies.append({"code": code, "detail": detail, "source": source})


def resolve_alias(
    payload: dict, aliases: list[str]
) -> tuple[str | None, Any | None, bool, list[dict]]:
    """Resolve a case-insensitive known alias, flagging disagreeing duplicates.

    SEC has shipped both ``investorWebsite`` and ``investorwebsite`` for the
    same field. Conflicting values are reported as ``alias_conflict`` instead
    of being silently resolved to whichever key happened to sort first.
    """
    anomalies: list[dict] = []
    lowered = {alias.lower() for alias in aliases}
    matches = [key for key in payload if key.lower() in lowered]
    if not matches:
        return (aliases[0], None, False, anomalies)
    canonical = next((alias for alias in aliases if alias in matches), matches[0])
    value = payload[canonical]
    conflicting = False
    for other in matches:
        if other != canonical and payload[other] != value:
            conflicting = True
            add_anomaly(
                anomalies,
                "alias_conflict",
                f"{canonical}={value!r} conflicts with {other}={payload[other]!r}",
                ",".join(matches),
            )
    return canonical, value, conflicting, anomalies


def normalize_cik_padded(raw: Any) -> str:
    """Return a 10-digit zero-padded CIK string from a raw integer or string."""
    text = str(raw or "").strip()
    return text.zfill(10)


def accession_normalized(raw: str | None) -> str | None:
    """Return the hyphen-free 18-digit accession, or ``None`` if unusable.

    Deliberately more permissive than :class:`~edgar_sec.domain.identity.AccessionNumber`:
    malformed accessions are data to be recorded and flagged here, not an
    exception that would discard the surrounding filing record.
    """
    if raw is None:
        return None
    text = str(raw).strip().replace("-", "")
    if not text.isdigit() or len(text) != 18:
        return None
    return text


def build_archive_url(
    cik_padded: str, accession_raw: str | None, primary_document: str | None
) -> tuple[str | None, str | None]:
    """Derive the archive document URL, returning ``(url, fallback_reason)``.

    A filing record must survive a null or stub primary document. The raw API
    value is kept on the record and the fallback is explained by the returned
    reason rather than applied silently.
    """
    accession_norm = accession_normalized(accession_raw)
    if accession_norm is None:
        return None, f"invalid accession {accession_raw!r}"
    if not primary_document or not str(primary_document).strip():
        return None, "primary_document_missing"
    doc = str(primary_document).strip()
    url = archives_url(cik_padded, accession_norm, doc)
    if doc.endswith((".txt", "0001.htm")):
        return url, f"primary_document_stub:{doc}"
    return url, None


def normalize_items(value: Any) -> list[str]:
    """Normalize filing items, which are codes in recent history but may be
    comma-joined strings in older historical files."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return [str(value)]


def to_bool(value: Any) -> bool | None:
    """Coerce SEC 0/1 integers and boolean strings, preserving ``None``."""
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("true", "1"):
            return True
        if lowered in ("false", "0", ""):
            return False if lowered else None
    return None


def to_int(value: Any) -> int | None:
    """Coerce a numeric value, returning ``None`` for anything non-integral."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None
