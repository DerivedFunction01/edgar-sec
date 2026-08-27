"""CSV manifest validation, CIK normalization, and stable ordering."""

from __future__ import annotations

import csv
import hashlib
import json
import re
from dataclasses import dataclass

CIK_PADDED_LEN = 10


@dataclass(frozen=True)
class TargetRow:
    cik_padded: str
    name: str
    source_row: int


class ManifestError(Exception):
    pass


def normalize_cik(raw: str) -> str:
    """Normalize a CIK to ten zero-padded digits. Raises ValueError when the
    value cannot be a CIK."""
    if raw is None:
        raise ValueError("cik is empty")
    text = str(raw).strip()
    if not text:
        raise ValueError("cik is empty")
    if not re.fullmatch(r"[0-9]+", text):
        raise ValueError(f"cik '{raw}' is not numeric")
    padded = text.zfill(CIK_PADDED_LEN)
    if len(padded) > CIK_PADDED_LEN:
        raise ValueError(f"cik '{raw}' exceeds {CIK_PADDED_LEN} digits")
    return padded


def canonical_json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def input_fingerprint(rows: list[TargetRow]) -> str:
    """Stable fingerprint of the normalized acquisition target list."""
    payload = [{"cik": row.cik_padded, "name": row.name} for row in rows]
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def read_input_manifest(path: str, limit: int | None = None):
    """Read and validate the CIK/name CSV.

    Returns (targets, report) where targets are deterministically sorted by
    cik_padded, and report describes malformed/duplicate rows. The input list
    is an acquisition target list, not a source of truth for profile fields.
    """
    malformed: list[dict] = []
    seen: dict[str, int] = {}
    duplicates: list[dict] = []
    rows: list[TargetRow] = []

    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        fieldnames = reader.fieldnames or []
        lowered = [name.strip().lower() for name in fieldnames]
        if "cik" not in lowered:
            raise ManifestError(f"{path}: input CSV must contain a 'cik' column")
        cik_key = fieldnames[lowered.index("cik")]
        name_key = fieldnames[lowered.index("name")] if "name" in lowered else None

        for row_number, record in enumerate(reader, start=2):  # header is row 1
            raw_cik = (record.get(cik_key) or "").strip()
            raw_name = (record.get(name_key) or "").strip() if name_key else ""
            if not raw_cik and not raw_name:
                continue  # tolerate fully empty lines
            try:
                cik_padded = normalize_cik(raw_cik)
            except ValueError as exc:
                malformed.append({"row": row_number, "cik": raw_cik, "name": raw_name, "error": str(exc)})
                continue
            if cik_padded in seen:
                duplicates.append(
                    {"row": row_number, "cik": cik_padded, "first_row": seen[cik_padded], "name": raw_name}
                )
                continue
            seen[cik_padded] = row_number
            rows.append(TargetRow(cik_padded=cik_padded, name=raw_name, source_row=row_number))
            if limit is not None and len(rows) >= limit:
                break

    rows.sort(key=lambda row: row.cik_padded)
    report = {
        "path": path,
        "fieldnames": fieldnames,
        "row_count": len(rows),
        "malformed": malformed,
        "duplicates": duplicates,
        "fingerprint": input_fingerprint(rows),
    }
    if not rows:
        raise ManifestError(f"{path}: no valid CIK rows found")
    return rows, report
