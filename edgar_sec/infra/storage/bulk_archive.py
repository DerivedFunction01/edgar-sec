"""Content-addressed store for SEC bulk archives, keyed by source id.

An archive is stored once per distinct payload: the payload file, a JSON
manifest, and a parquet member index extracted from its central directory.
"""

from __future__ import annotations

import json
import os
import shutil
import struct
import zipfile
import zlib
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa

from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.foundation.runtime.settings import resolve_settings

from .atomic import _fsync_dir, atomic_write_json
from .duckdb import connect
from .parquet import read_parquet_table, write_parquet_table

_LOCAL_HEADER = struct.Struct("<IHHHHHIIIHH")
_LOCAL_HEADER_SIGNATURE = 0x04034B50
_STORED = 0
_DEFLATE = 8

ARCHIVE_FILE_NAME = "archive.zip"
MANIFEST_FILE_NAME = "manifest.json"
MEMBER_INDEX_FILE_NAME = "members.parquet"
RETENTION_SETTING_PATH = "sec.bulk_archive.retention"

MEMBER_INDEX_SCHEMA = pa.schema(
    [
        ("member_name", pa.string(), False),
        ("crc32", pa.int64(), False),
        ("compressed_size", pa.int64(), False),
        ("uncompressed_size", pa.int64(), False),
        ("header_offset", pa.int64(), False),
    ]
)

__all__ = [
    "ARCHIVE_FILE_NAME",
    "MANIFEST_FILE_NAME",
    "MEMBER_INDEX_FILE_NAME",
    "MEMBER_INDEX_SCHEMA",
    "ArchiveReference",
    "BulkArchiveManifest",
    "BulkArchiveStore",
]


@dataclass(frozen=True, slots=True)
class BulkArchiveManifest:
    """Provenance of one stored archive, persisted beside its payload."""

    source_id: str
    source_url: str
    sha256: str
    byte_size: int
    member_count: int
    fetched_at: str
    sec_last_modified: str | None = None


@dataclass(frozen=True, slots=True)
class ArchiveReference:
    """Resolved location of one stored archive and its member index."""

    source_id: str
    sha256: str
    path: Path
    manifest: BulkArchiveManifest
    member_index_path: Path


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _resolve_retention() -> int:
    resolved = resolve_settings(include=["sec"])
    return int(resolved[RETENTION_SETTING_PATH])


def _write_member_index(payload: Path, destination: Path) -> int:
    """Extract the central directory of ``payload`` into a parquet index."""
    with zipfile.ZipFile(payload) as archive:
        infos = archive.infolist()
    table = pa.table(
        {
            "member_name": [info.filename for info in infos],
            "crc32": [int(info.CRC) for info in infos],
            "compressed_size": [int(info.compress_size) for info in infos],
            "uncompressed_size": [int(info.file_size) for info in infos],
            "header_offset": [int(info.header_offset) for info in infos],
        },
        schema=MEMBER_INDEX_SCHEMA,
    )
    write_parquet_table(table, destination)
    return len(infos)


class BulkArchiveStore:
    """Stores bulk archives under ``<root>/<source-id>/<sha256>/``."""

    def __init__(self, root: str | Path, *, retention: int | None = None) -> None:
        self.root = Path(root)
        self._retention = retention

    @property
    def retention(self) -> int:
        """Archives kept per source; resolved from settings when unset."""
        if self._retention is not None:
            return self._retention
        return _resolve_retention()

    def put_file(
        self,
        source_id: str,
        source_path: str | Path,
        *,
        source_url: str,
        fetched_at: str | None = None,
        sec_last_modified: str | None = None,
    ) -> ArchiveReference:
        """Store one archive payload; identical bytes are a no-op."""
        source = Path(source_path)
        sha256 = file_sha256(source)
        existing = self._reference(source_id, sha256)
        if existing is not None:
            return existing
        final_dir = self.root / source_id / sha256
        staging = self.root / source_id / f".staging-{sha256}-{os.getpid()}"
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True)
        try:
            payload = staging / ARCHIVE_FILE_NAME
            shutil.copyfile(source, payload)
            member_count = _write_member_index(
                payload, staging / MEMBER_INDEX_FILE_NAME
            )
            manifest = BulkArchiveManifest(
                source_id=source_id,
                source_url=source_url,
                sha256=sha256,
                byte_size=source.stat().st_size,
                member_count=member_count,
                fetched_at=fetched_at or _utc_now(),
                sec_last_modified=sec_last_modified,
            )
            atomic_write_json(staging / MANIFEST_FILE_NAME, asdict(manifest))
            if final_dir.exists():
                shutil.rmtree(final_dir)
            os.replace(staging, final_dir)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        _fsync_dir(str(final_dir.parent))
        self._prune(source_id)
        reference = self._reference(source_id, sha256)
        if reference is None:
            raise RuntimeError(f"stored archive {sha256} for {source_id} is unreadable")
        return reference

    def open(
        self, source_id: str, sha256: str | None = None
    ) -> ArchiveReference | None:
        """Reference for one archive, or the newest stored when ``sha256`` is None."""
        if sha256 is not None:
            return self._reference(source_id, sha256)
        archives = self.list_archives(source_id)
        return archives[0] if archives else None

    def list_archives(self, source_id: str) -> list[ArchiveReference]:
        """All stored archives for a source, newest first."""
        source_dir = self.root / source_id
        if not source_dir.is_dir():
            return []
        references = []
        for child in source_dir.iterdir():
            if not child.is_dir() or child.name.startswith("."):
                continue
            reference = self._reference(source_id, child.name)
            if reference is not None:
                references.append(reference)
        references.sort(
            key=lambda ref: (ref.manifest.fetched_at, ref.sha256), reverse=True
        )
        return references

    def member_index(self, reference: ArchiveReference) -> pa.Table:
        """The member index table of a stored archive."""
        return read_parquet_table(reference.member_index_path)

    def read_member(self, reference: ArchiveReference, member_name: str) -> bytes:
        """One member's bytes, read from the stored archive in place.

        Located through the stored member index, so the archive's central
        directory is never materialized for a single-member read.
        """
        con = connect()
        try:
            row = con.execute(
                "SELECT header_offset, compressed_size, uncompressed_size, crc32 "
                "FROM read_parquet(?) WHERE member_name = ?",
                [str(reference.member_index_path), member_name],
            ).fetchone()
        finally:
            con.close()
        if row is None:
            raise ValueError(
                f"member {member_name!r} is not in archive {reference.sha256}"
            )
        header_offset, compressed_size, uncompressed_size, crc32 = (
            int(value) for value in row
        )
        with open(reference.path, "rb") as handle:
            header = _LOCAL_HEADER.unpack(
                os.pread(handle.fileno(), _LOCAL_HEADER.size, header_offset)
            )
            if header[0] != _LOCAL_HEADER_SIGNATURE:
                raise zipfile.BadZipFile(f"member {member_name!r} has no local header")
            flags, method = header[2], header[3]
            if flags & 0x1:
                raise ValueError(f"member {member_name!r} is encrypted")
            data_at = header_offset + _LOCAL_HEADER.size + header[9] + header[10]
            raw = os.pread(handle.fileno(), compressed_size, data_at)
        if method == _STORED:
            payload = raw
        elif method == _DEFLATE:
            payload = zlib.decompress(raw, wbits=-zlib.MAX_WBITS)
        else:
            raise ValueError(
                f"member {member_name!r} uses unsupported compression {method}"
            )
        if len(payload) != uncompressed_size or zlib.crc32(payload) != crc32:
            raise zipfile.BadZipFile(f"member {member_name!r} fails its CRC check")
        return payload

    def _reference(self, source_id: str, sha256: str) -> ArchiveReference | None:
        archive_dir = self.root / source_id / sha256
        manifest_path = archive_dir / MANIFEST_FILE_NAME
        payload = archive_dir / ARCHIVE_FILE_NAME
        index_path = archive_dir / MEMBER_INDEX_FILE_NAME
        if not (manifest_path.is_file() and payload.is_file() and index_path.is_file()):
            return None
        try:
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest = BulkArchiveManifest(
                source_id=str(raw["source_id"]),
                source_url=str(raw["source_url"]),
                sha256=str(raw["sha256"]),
                byte_size=int(raw["byte_size"]),
                member_count=int(raw["member_count"]),
                fetched_at=str(raw["fetched_at"]),
                sec_last_modified=raw.get("sec_last_modified"),
            )
        except (KeyError, TypeError, ValueError):
            return None
        if manifest.sha256 != sha256:
            return None
        return ArchiveReference(
            source_id=source_id,
            sha256=sha256,
            path=payload,
            manifest=manifest,
            member_index_path=index_path,
        )

    def _prune(self, source_id: str) -> None:
        keep = self.retention
        for reference in self.list_archives(source_id)[keep:]:
            shutil.rmtree(self.root / source_id / reference.sha256)
