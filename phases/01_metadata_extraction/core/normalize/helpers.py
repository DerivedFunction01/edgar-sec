"""Shared normalization helpers, parsing utilities, and anomaly recording."""

from __future__ import annotations

import hashlib
import re
from typing import Any

from defs.storage import canonical_json

SEC_ARCHIVE_BASE = "https://www.sec.gov/Archives/edgar/data"
SEC_SUBMISSIONS_BASE = "https://data.sec.gov/submissions"

ACCESSION_RE = re.compile(r"^\d{10}-\d{2}-\d{6}$")


def add_anomaly(
    anomalies: list[dict], code: str, detail: str, source: str = ""
) -> None:
    anomalies.append({"code": code, "detail": detail, "source": source})


def resolve_alias(
    payload: dict, aliases: list[str]
) -> tuple[str | None, Any | None, bool, list[dict]]:
    """Resolve case-insensitive known aliases.

    Returns (canonical_key, value, conflicting, anomalies). Conflicting
    aliases with different values are flagged, never silently chosen.
    """
    anomalies: list[dict] = []
    matches = [key for key in payload if key.lower() in {a.lower() for a in aliases}]
    if not matches:
        return (aliases[0], None, False, anomalies)
    canonical = next((a for a in aliases if a in matches), matches[0])
    value = payload[canonical]
    conflicting = False
    for other in matches:
        if other != canonical and payload[other] != value:
            conflicting = True
            anomalies.append(
                {
                    "code": "alias_conflict",
                    "detail": f"{canonical}={value!r} conflicts with {other}={payload[other]!r}",
                    "source": ",".join(matches),
                }
            )
    return canonical, value, conflicting, anomalies


def normalize_cik_padded(raw: Any) -> str:
    text = str(raw or "").strip()
    digits = text.zfill(10)
    return digits


def accession_normalized(raw: str | None) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip().replace("-", "")
    if not text.isdigit() or len(text) != 18:
        return None
    return text


def build_archive_url(
    cik_padded: str, accession_raw: str | None, primary_document: str | None
) -> tuple[str | None, str | None]:
    """Derive the archive URL from CIK, accession, and primary document.

    Returns (url, fallback_reason). A filing record must survive even when
    ``primaryDocument`` is null or an unusual stub; the raw API value is
    retained on the record and any fallback selection is explained by the
    returned reason instead of being applied silently.
    """
    accession_norm = accession_normalized(accession_raw)
    if accession_norm is None:
        return None, f"invalid accession {accession_raw!r}"
    cik_int = str(int(cik_padded))
    if not primary_document or not str(primary_document).strip():
        return None, "primary_document_missing"
    doc = str(primary_document).strip()
    url = f"{SEC_ARCHIVE_BASE}/{cik_int}/{accession_norm}/{doc}"
    if doc.endswith((".txt", "0001.htm")):
        return url, f"primary_document_stub:{doc}"
    return url, None


def to_bool(value: Any) -> bool | None:
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
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def sha256_of(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


__all__ = [
    "ACCESSION_RE",
    "SEC_ARCHIVE_BASE",
    "SEC_SUBMISSIONS_BASE",
    "accession_normalized",
    "add_anomaly",
    "build_archive_url",
    "canonical_json",
    "normalize_cik_padded",
    "resolve_alias",
    "sha256_of",
    "to_bool",
    "to_int",
]
