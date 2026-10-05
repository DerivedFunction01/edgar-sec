"""The vocabulary of a browsable artifact.

A dataset is addressed by an opaque id, never a path — a caller that could name a
path could ask for anything on disk. A multipart dataset has one id, not one per part.
"""

from __future__ import annotations

import base64
import hashlib
import os
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from edgar_sec.foundation.hashing import file_sha256

__all__ = [
    "ArtifactSummary",
    "DatasetError",
    "artifact_id",
    "artifact_path",
    "artifact_table",
    "compute_revision",
    "compute_union_revision",
    "summary_to_dict",
]

# Separator between a dataset's logical path and an optional SQLite table name.
# ``::`` cannot appear in a generated artifact path, and it survives the base64
# round trip unchanged, so the split is unambiguous after decoding.
_TABLE_SEPARATOR = "::"


class DatasetError(ValueError):
    """An artifact could not be read as a dataset."""


@dataclass(frozen=True)
class ArtifactSummary:
    """One browsable dataset.

    Field names are part of the HTTP contract: the browser's compiled bundle reads them.
    """

    id: str
    relative_path: str
    phase: str | None
    run_id: str | None
    kind: str
    format: str
    size_bytes: int
    mtime: str | None
    revision: str = ""
    source_paths: tuple[str, ...] = ()
    table: str | None = None


def artifact_id(relative_path: str | Path, table: str | None = None) -> str:
    """Return a URL-safe opaque id for a dataset's path relative to the root."""
    posix = (
        Path(relative_path).as_posix()
        if isinstance(relative_path, Path)
        else str(relative_path)
    )
    if table:
        posix = f"{posix}{_TABLE_SEPARATOR}{table}"
    return base64.urlsafe_b64encode(posix.encode("utf-8")).decode("ascii")


def decode_artifact_id(value: str) -> tuple[str, str | None]:
    """Decode an id to ``(relative_path, table)``; raises ``DatasetError``."""
    try:
        decoded = base64.urlsafe_b64decode(value.encode("ascii")).decode("utf-8")
    except Exception as exc:
        raise DatasetError(f"invalid dataset id: {value!r}") from exc
    if _TABLE_SEPARATOR in decoded:
        path, _, table = decoded.partition(_TABLE_SEPARATOR)
        return path, table or None
    return decoded, None


def artifact_path(artifact_id_value: str, root: Path) -> Path:
    """Resolve an id to a path, refusing anything outside ``root``.

    Compares against the *resolved* root and the candidate's parents, so ``..``
    segments and symlinks collapse before the comparison, not after.
    """
    relative, _ = decode_artifact_id(artifact_id_value)
    base_relative = relative.split(_TABLE_SEPARATOR)[0]
    candidate = (Path(root) / base_relative).resolve()
    root_resolved = Path(root).resolve()
    if candidate != root_resolved and root_resolved not in candidate.parents:
        raise DatasetError("dataset path escapes the artifacts root")
    return candidate


def artifact_table(artifact_id_value: str) -> str | None:
    """Return the SQLite table name encoded in an id, if any."""
    try:
        return decode_artifact_id(artifact_id_value)[1]
    except DatasetError:
        return None


def compute_revision(size_bytes: int, mtime_ns: int) -> str:
    """Change token for a single file: size plus nanosecond mtime.

    Only sound for unpublished files; a published snapshot's manifest digest is
    stronger (see ``manifest_revision``).
    """
    return f"{size_bytes}:{mtime_ns}"


def manifest_revision(manifest_path: Path) -> str:
    """Content-addressed change token for a published dataset.

    Its own bytes are the identity because published manifests are immutable, and a
    digest cannot miss a change the way a filesystem timestamp can.
    """
    return file_sha256(manifest_path)[:16]


def compute_union_revision(items: Iterable[ArtifactSummary]) -> str:
    """Composite change token for a transient run union.

    A run with no manifest is still accumulating, so the token digests sorted
    ``relative_path:revision`` triples plus the file count.
    """
    materialized = list(items)
    tokens = sorted(
        f"{item.relative_path}:{item.revision}"
        for item in materialized
        if item.revision
    )
    digest = hashlib.sha256("|".join(tokens).encode("utf-8")).hexdigest()[:16]
    return f"{digest}:{len(materialized)}"


def mtime_iso(path: Path) -> str | None:
    """Return a file's mtime as an ISO-8601 UTC string, or ``None`` if unset."""
    try:
        seconds = path.stat().st_mtime
    except OSError:
        return None
    if seconds <= 0:
        return None
    return datetime.fromtimestamp(seconds, tz=UTC).isoformat()


def file_size(path: Path) -> int:
    """Return a file's size in bytes, or ``0`` when it cannot be stat'd."""
    try:
        return path.stat().st_size
    except OSError:
        return 0


def newest_mtime(paths: Iterable[Path]) -> str | None:
    """Return the latest ISO mtime across a set of files."""
    stamps = [mtime_iso(path) for path in paths]
    present = [stamp for stamp in stamps if stamp]
    return max(present) if present else None


def walk_files(root: Path) -> Iterable[Path]:
    """Yield every file under ``root``, skipping dot-directories.

    A stray ``.git`` under the artifacts root would make a listing an unbounded walk.
    Symlinked directories are not followed.
    """
    for current, dirs, files in os.walk(root):
        dirs[:] = [name for name in dirs if not name.startswith(".")]
        for name in files:
            if name.startswith("."):
                continue
            yield Path(current) / name


def summary_to_dict(summary: ArtifactSummary) -> dict:
    """Convert a summary to its wire representation."""
    return asdict(summary)
