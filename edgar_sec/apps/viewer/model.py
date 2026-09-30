"""The vocabulary of a browsable artifact.

A single record type and the functions that turn one into a wire-safe identity.
Kept separate from the loaders that produce these records and from the walk that
collects them, so that neither imports the other.

Two rules shape the identity design:

**A dataset is addressed by an opaque id, never by a path.** The browser sends
``id``; the server turns it back into a path. That is what confines a request to
the artifacts root — a caller that could name a path could ask for anything on
disk.

**A multipart dataset has one id, not one per part.** The parts are a property
of the record (``source_paths``), not separate browsable things. An operator
thinks "the Phase 1 snapshot", not "part 0 of 37"; splitting them would make the
sidebar a file listing and lose the fact that they are one dataset.
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

    The field names are part of the HTTP contract: the browser's compiled bundle
    reads these keys directly. Renaming one is a breaking API change, not a
    refactor.
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
    """Decode an id back to ``(relative_path, table)``.

    Raises ``DatasetError`` on anything that is not a valid encoding, so a caller
    passing garbage gets one error type rather than two.
    """
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

    The confinement check is the reason ids are opaque. It compares against the
    *resolved* root and the candidate's parents, which also collapses ``..``
    segments and symlinks before the comparison rather than after.
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

    Only sound for files that are not yet published. A published snapshot is
    immutable, so its manifest digest is the stronger token; see
    :func:`manifest_revision`.
    """
    return f"{size_bytes}:{mtime_ns}"


def manifest_revision(manifest_path: Path) -> str:
    """Content-addressed change token for a published dataset.

    A published manifest is immutable — the pipelines refuse to overwrite one —
    so its own bytes are the dataset's identity. This is strictly better than a
    stat-based token: it cannot miss a change, and it does not need a filesystem
    timestamp whose resolution depends on the mount.
    """
    return file_sha256(manifest_path)[:16]


def compute_union_revision(items: Iterable[ArtifactSummary]) -> str:
    """Composite change token for a transient run union.

    A run with no manifest yet is still accumulating, so there is nothing
    content-addressed to hash. The token is a digest over the sorted per-file
    ``relative_path:size:mtime_ns`` triples plus the file count, so adding,
    removing, or rewriting any chunk invalidates the cached listing for the
    union.
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

    Dot-directories are skipped rather than descended so a stray ``.git`` or
    editor directory under the artifacts root cannot turn a listing into an
    unbounded walk. Symlinked directories are not followed.
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
