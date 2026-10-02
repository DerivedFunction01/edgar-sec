"""Input CIK manifest ingestion and fingerprinting.

The manifest is the reproducibility root of a run: its SHA-256 digest is the
``input_fingerprint`` recorded in the plan, in every row, and in the published
snapshot manifest. Malformed rows are reported rather than silently dropped.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

from edgar_sec.domain.identity import Cik
from edgar_sec.foundation.hashing import file_sha256

MAX_CIK_VALUE = 9_999_999_999

__all__ = ["InputManifest", "read_cik_manifest"]


@dataclass(frozen=True, slots=True)
class InputManifest:
    """Normalized CIK list plus the fingerprint that identifies the input."""

    input_name: str
    input_path: Path
    input_fingerprint: str
    ciks: tuple[str, ...]
    names: tuple[str, ...] = ()
    skipped: tuple[dict, ...] = field(default=())
    duplicate_count: int = 0

    @property
    def row_count(self) -> int:
        """Number of usable, deduplicated CIKs."""
        return len(self.ciks)

    def name_for(self, cik: str) -> str:
        """Curated display name for a CIK, or an empty string when unnamed."""
        if not self.names:
            return ""
        index = self.ciks.index(cik)
        return self.names[index]


def _parse_cik(raw: str) -> str | None:
    """Return a 10-digit CIK string, or ``None`` when the cell is unusable.

    Validation happens on the raw text before any integer conversion:
    ``Cik.from_raw("")`` deliberately yields CIK zero, which would let an
    empty manifest row masquerade as a real registrant.
    """
    text = raw.strip()
    if not text or not text.isdigit():
        return None
    value = int(text)
    if value <= 0 or value > MAX_CIK_VALUE:
        return None
    return Cik(value).to_10digit()


def read_cik_manifest(input_path: str | Path) -> InputManifest:
    """Read a CIK CSV into a fingerprinted, normalized manifest.

    A header row is detected by the absence of a leading digit in the first
    cell. Duplicate CIKs keep their first position. Rows that cannot be parsed
    are collected in ``skipped`` rather than raising, so one bad line does not
    abort a large ingest.
    """
    path = Path(input_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"input manifest not found: {path}")

    ciks: list[str] = []
    names: list[str] = []
    seen: set[str] = set()
    skipped: list[dict] = []
    duplicates = 0

    with path.open(newline="", encoding="utf-8-sig") as handle:
        for line_number, row in enumerate(csv.reader(handle), start=1):
            if not row or not any(cell.strip() for cell in row):
                continue
            raw = row[0]
            if line_number == 1 and not raw.strip().isdigit():
                continue
            cik = _parse_cik(raw)
            if cik is None:
                skipped.append({"line": line_number, "value": raw, "reason": "invalid"})
                continue
            if cik in seen:
                duplicates += 1
                continue
            seen.add(cik)
            ciks.append(cik)
            names.append(row[1].strip() if len(row) > 1 else "")

    if not ciks:
        raise ValueError(f"input manifest contains no usable CIKs: {path}")

    return InputManifest(
        input_name=path.name,
        input_path=path,
        input_fingerprint=file_sha256(path),
        ciks=tuple(ciks),
        names=tuple(names),
        skipped=tuple(skipped),
        duplicate_count=duplicates,
    )
