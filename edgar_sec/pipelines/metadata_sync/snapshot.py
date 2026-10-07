"""Resolve a published metadata snapshot to a validated, ordered part list.
The list is read from the manifest, never by globbing. A file absent from the list
is untrusted data; a listed file absent from disk is an incomplete publication,
and the two are different errors.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from edgar_sec.foundation.hashing import file_sha256

__all__ = [
    "SNAPSHOT_MANIFEST_VERSION",
    "SnapshotLayout",
    "SnapshotParts",
    "load_snapshot_manifest",
    "read_snapshot_parts",
    "resolve_part_path",
]

SNAPSHOT_MANIFEST_VERSION = "2.0.0"
"""Manifest version carrying an explicit ordered part list.

A manifest without this version is a legacy single-part manifest and is read
through the ``output_path``/``artifact_sha256`` pair it already carries.
"""


class SnapshotLayoutError(ValueError):
    """A published snapshot manifest does not describe a readable dataset."""


@dataclass(frozen=True, slots=True)
class SnapshotLayout:
    """How one snapshot manifest describes its payload."""

    manifest_path: Path
    manifest: dict[str, Any]
    multipart: bool
    snapshot_id: str
    row_count: int
    schema_version: str


@dataclass(frozen=True, slots=True)
class SnapshotParts:
    """A snapshot resolved to ordered Parquet parts."""

    layout: SnapshotLayout
    paths: tuple[Path, ...]
    part_count: int
    row_count: int

    def sql_sources(self) -> list[str]:
        """SQL ``read_parquet`` arguments for the whole snapshot."""
        return [str(path) for path in self.paths]


def load_snapshot_manifest(manifest_path: str | Path) -> SnapshotLayout:
    """Read a snapshot manifest and describe its layout."""
    path = Path(manifest_path)
    if not path.is_file():
        raise FileNotFoundError(f"snapshot manifest not found: {path}")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise SnapshotLayoutError(f"snapshot manifest is not a JSON object: {path}")

    parts = manifest.get("parts")
    if parts is None and manifest.get("relations"):
        parts = manifest["relations"].get("submissions", ())
    if not parts:
        raise SnapshotLayoutError(
            f"snapshot manifest names no payload: {path}; expected a 'parts' list "
            "or 'relations'"
        )
    row_count = int(manifest.get("row_count") or 0)
    if not row_count and manifest.get("relations"):
        submissions_rel = manifest["relations"].get("submissions", ())
        row_count = sum(int(p.get("row_count", 0)) for p in submissions_rel)

    return SnapshotLayout(
        manifest_path=path,
        manifest=manifest,
        multipart=True,
        snapshot_id=str(manifest.get("snapshot_id") or ""),
        row_count=row_count,
        schema_version=str(manifest.get("schema_version") or ""),
    )


def resolve_part_path(manifest_path: Path, value: str) -> Path:
    """Resolve a manifest-relative or absolute artifact path.
    A relative part path resolves against the manifest's directory.
    """
    candidate = Path(value)
    if candidate.is_absolute():
        return candidate
    return (manifest_path.parent / candidate).resolve()


def read_snapshot_parts(
    manifest_path: str | Path, *, verify_digests: bool = True
) -> SnapshotParts:
    """Resolve a snapshot manifest to its ordered part list and verify it.
    Digests are checked by default: an unchecked list admits a truncated snapshot.
    """
    layout = load_snapshot_manifest(manifest_path)
    manifest = layout.manifest
    anchor = layout.manifest_path

    paths: list[Path] = []
    seen: set[str] = set()
    raw_parts = manifest.get("parts")
    if raw_parts is None and manifest.get("relations"):
        raw_parts = manifest["relations"].get("submissions", ())
    parts_list = list(raw_parts or ())

    for index, part in enumerate(parts_list):
        name = str(part.get("path") or "")
        if not name:
            raise SnapshotLayoutError(
                f"snapshot part {index} in {layout.manifest_path} names no path"
            )
        if name in seen:
            raise SnapshotLayoutError(
                f"snapshot part {index} in {layout.manifest_path} repeats path {name!r}"
            )
        seen.add(name)
        path = resolve_part_path(anchor, name)
        if not path.is_file():
            raise SnapshotLayoutError(
                f"snapshot part {name} named by {layout.manifest_path} is missing: "
                f"{path}; the snapshot was not fully published"
            )
        if verify_digests:
            expected = str(part.get("sha256") or "")
            if not expected:
                raise SnapshotLayoutError(
                    f"snapshot part {name} in {layout.manifest_path} has no digest"
                )
            actual = file_sha256(path)
            if actual != expected:
                raise SnapshotLayoutError(
                    f"snapshot part {name} digest mismatch: manifest {expected}, "
                    f"file {actual}"
                )
        paths.append(path)

    if not paths:
        raise SnapshotLayoutError(
            f"snapshot manifest lists no parts: {layout.manifest_path}"
        )
    return SnapshotParts(
        layout=layout,
        paths=tuple(paths),
        part_count=len(paths),
        row_count=layout.row_count,
    )
