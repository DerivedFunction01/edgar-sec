"""Companyfacts bulk archive: download leg, member planning, normalization.

Normalization mirrors ``apps.client.companyfacts.iter_company_facts`` field
for field; pipelines may not import the apps layer, so the mapping lives here.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import pyarrow as pa

from edgar_sec.domain.sec_urls import COMPANYFACTS_BULK_URL, companyfacts_bulk_url
from edgar_sec.foundation.hashing import file_sha256, sha256_bytes
from edgar_sec.infra.sec_http.client import SecHttpClient
from edgar_sec.infra.sec_http.streaming import StreamFailure
from edgar_sec.infra.storage.bulk_archive import ArchiveReference, BulkArchiveStore
from edgar_sec.infra.storage.member_index import MemberIndex, ensure_member_index

__all__ = [
    "COMPANYFACTS_BULK_SOURCE_ID",
    "FACTS_SCHEMA",
    "CompanyFactsArchive",
    "MemberPlan",
    "member_fingerprint",
    "normalize_member",
    "plan_members",
]

COMPANYFACTS_BULK_SOURCE_ID = "companyfacts_bulk"

_MEMBER_RE = re.compile(r"^CIK(\d{10})\.json$")

FACTS_SCHEMA = pa.schema(
    [
        ("cik", pa.int64(), False),
        ("taxonomy", pa.string(), False),
        ("tag", pa.string(), False),
        ("unit", pa.string(), False),
        ("start", pa.string(), False),
        ("end", pa.string(), False),
        ("accession", pa.string(), False),
        ("form", pa.string(), False),
        ("filed", pa.string(), False),
        ("fiscal_year", pa.int64(), True),
        ("fiscal_period", pa.string(), False),
        ("frame", pa.string(), False),
        ("value", pa.float64(), False),
    ]
)


def _validate_companyfacts_redirect(url: str) -> None:
    """Bulk downloads may redirect only within the daily-index xbrl directory."""
    parts = urlsplit(url)
    expected = urlsplit(COMPANYFACTS_BULK_URL)
    if (
        parts.scheme != "https"
        or parts.netloc != expected.netloc
        or not parts.path.startswith("/Archives/edgar/daily-index/xbrl/")
    ):
        raise ValueError(f"bulk redirect left the daily-index xbrl directory: {url}")


@dataclass(frozen=True, slots=True)
class MemberPlan:
    """One per-CIK member of a companyfacts archive, with its CRC fingerprint."""

    cik_padded: str
    member_name: str
    crc32: int
    fingerprint: str

    @property
    def cik(self) -> int:
        """The member's CIK as an integer."""
        return int(self.cik_padded)


def member_fingerprint(cik_padded: str, crc32: int) -> str:
    """Per-CIK fingerprint from the member CRC; the carry-forward key."""
    material = f"companyfacts-member-v1:{cik_padded}:{crc32}"
    return sha256_bytes(material.encode("utf-8"))


def plan_members(index: pa.Table) -> tuple[MemberPlan, ...]:
    """Plan an ingest from an archive member index, CIK-sorted.

    Members that are not per-CIK companyfacts documents are not planned.
    """
    plans: list[MemberPlan] = []
    names = index.column("member_name").to_pylist()
    crcs = index.column("crc32").to_pylist()
    for name, crc in zip(names, crcs, strict=True):
        match = _MEMBER_RE.fullmatch(str(name))
        if match is None:
            continue
        cik_padded = match.group(1)
        plans.append(
            MemberPlan(
                cik_padded=cik_padded,
                member_name=str(name),
                crc32=int(crc),
                fingerprint=member_fingerprint(cik_padded, int(crc)),
            )
        )
    plans.sort(key=lambda plan: plan.cik_padded)
    return tuple(plans)


def normalize_member(cik_padded: str, raw: bytes) -> tuple[str, pa.Table]:
    """Normalize one member document into fact rows keyed by the plan's key.

    Returns (entity name, rows). A member that is not a JSON object raises,
    because a corrupt member must fail the ingest, not silently drop a CIK.
    """
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"bulk member CIK{cik_padded}.json is not JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"bulk member CIK{cik_padded}.json is not a JSON object")
    columns: dict[str, list] = {name: [] for name in FACTS_SCHEMA.names}
    cik = int(cik_padded)
    facts = payload.get("facts")
    if isinstance(facts, dict):
        for taxonomy, concepts in facts.items():
            if not isinstance(concepts, dict):
                continue
            for tag, concept in concepts.items():
                if not isinstance(concept, dict):
                    continue
                units = concept.get("units")
                if not isinstance(units, dict):
                    continue
                for unit, points in units.items():
                    if not isinstance(points, list):
                        continue
                    for point in points:
                        _append_point(columns, cik, taxonomy, tag, unit, point)
    table = pa.table(columns, schema=FACTS_SCHEMA)
    return str(payload.get("entityName", "")), table


def _append_point(
    columns: dict[str, list],
    cik: int,
    taxonomy: object,
    tag: object,
    unit: object,
    point: object,
) -> None:
    if not isinstance(point, dict):
        return
    value = point.get("val")
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return
    fiscal_year = point.get("fy")
    columns["cik"].append(cik)
    columns["taxonomy"].append(str(taxonomy))
    columns["tag"].append(str(tag))
    columns["unit"].append(str(unit))
    columns["start"].append(str(point.get("start", "")))
    columns["end"].append(str(point.get("end", "")))
    columns["accession"].append(str(point.get("accn", "")))
    columns["form"].append(str(point.get("form", "")))
    columns["filed"].append(str(point.get("filed", "")))
    columns["fiscal_year"].append(fiscal_year if isinstance(fiscal_year, int) else None)
    columns["fiscal_period"].append(str(point.get("fp", "")))
    columns["frame"].append(str(point.get("frame", "")))
    columns["value"].append(float(value))


class CompanyFactsArchive:
    """One downloaded companyfacts bulk ZIP, opened for per-CIK reads."""

    def __init__(
        self,
        zip_path: str | Path,
        *,
        archive_sha256: str = "",
        member_index_path: str | Path | None = None,
    ) -> None:
        self.zip_path = Path(zip_path)
        self.archive_sha256 = archive_sha256 or file_sha256(self.zip_path)
        if member_index_path is None:
            member_index_path = ensure_member_index(self.zip_path, self.archive_sha256)
        self.member_index_path = Path(member_index_path)
        self._index = MemberIndex(self.member_index_path)
        self._zip_fd = os.open(self.zip_path, os.O_RDONLY)
        self.store_reference: ArchiveReference | None = None

    @classmethod
    def download(
        cls,
        http: SecHttpClient,
        store: BulkArchiveStore,
        *,
        max_bytes: int,
    ) -> "CompanyFactsArchive":
        """Stream the bulk ZIP once, store it, and open the stored copy."""
        url = companyfacts_bulk_url()
        staging_dir = store.root / ".downloads"
        staging_dir.mkdir(parents=True, exist_ok=True)
        descriptor, staging_name = tempfile.mkstemp(
            prefix="companyfacts-bulk-", suffix=".zip", dir=staging_dir
        )
        staging = Path(staging_name)
        try:
            os.close(descriptor)
            result = http.stream_to_file(
                url,
                staging,
                max_response_bytes=max_bytes,
                validate_redirect=_validate_companyfacts_redirect,
            )
            if isinstance(result, StreamFailure):
                raise RuntimeError(
                    f"companyfacts download failed ({result.code}): {result.detail}"
                )
            reference = store.put_file(
                COMPANYFACTS_BULK_SOURCE_ID, staging, source_url=url
            )
        finally:
            staging.unlink(missing_ok=True)
        archive = cls(reference.path, archive_sha256=reference.sha256)
        archive.store_reference = reference
        return archive

    def close(self) -> None:
        self._index.close()
        os.close(self._zip_fd)

    def read_member(self, member_name: str) -> bytes | None:
        """One member's bytes through the memory-mapped member index."""
        return self._index.read_member(self._zip_fd, member_name)
