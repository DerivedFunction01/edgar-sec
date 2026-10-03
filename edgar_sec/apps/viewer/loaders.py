"""One loader per published dataset type.

Each loader **knows** the manifest of a dataset it owns and asks the owning
pipeline or ``infra.storage`` to interpret it, so the only thing guessed is the
dataset's own root — one known path per pipeline, not a pattern. Inferring a
dataset's role from a directory name's shape would have to be taught every naming
convention and would silently mislabel anything that did not fit one. Adding a
dataset means adding a loader, not extending a naming table.

The pipeline manifests are not one vocabulary, which is why this module is a
registry rather than a single function:

| Dataset | Manifest | Read by |
| :--- | :--- | :--- |
| ``metadata`` | ``metadata.manifest.json`` | ``metadata_sync.snapshot.read_snapshot_parts`` |
| ``filing_catalog`` | ``snapshot.manifest.json`` | this module (it owns the keys) |
| ``document_storage`` | ``manifest.json`` | ``infra.storage.manifests.SnapshotReader`` |

A published dataset becomes browsable only if its manifest is present and its
declared parts exist: an in-flight run has no manifest, and a manifest naming a
missing part means the publication did not finish. Neither is silently shown as a
shorter dataset than it is.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from edgar_sec.apps.viewer.model import (
    ArtifactSummary,
    DatasetError,
    artifact_id,
    compute_union_revision,
    file_size,
    manifest_revision,
    mtime_iso,
    newest_mtime,
    walk_files,
)
from edgar_sec.infra.storage.manifests import (
    PART_KIND_INDEX,
    PART_KIND_PAYLOAD,
    SnapshotReader,
    resolved_parts,
)
from edgar_sec.pipelines.filing_catalog.paths import (
    SNAPSHOT_FILE_NAME,
    TARGETS_DIR_NAME,
    FilingCatalogPaths,
)
from edgar_sec.pipelines.filing_catalog.paths import (
    SNAPSHOT_MANIFEST_NAME as CATALOG_MANIFEST_NAME,
)
from edgar_sec.pipelines.metadata_sync.paths import (
    METADATA_DIR,
    MetadataPaths,
)
from edgar_sec.pipelines.metadata_sync.paths import (
    SNAPSHOT_MANIFEST_NAME as METADATA_MANIFEST_NAME,
)
from edgar_sec.pipelines.metadata_sync.snapshot import (
    SnapshotLayoutError,
    read_snapshot_parts,
)

log = logging.getLogger("apps.viewer.loaders")

__all__ = [
    "LOADERS",
    "DatasetLoader",
    "iter_documents",
    "load_document_storage",
    "load_filing_catalog",
    "load_metadata",
    "load_sqlite_databases",
    "load_transient_runs",
    "run_all",
]

_TRANSIENT_DATASETS = (METADATA_DIR, "filing_catalog", "document_storage")
_DATA_SUFFIXES = {".parquet", ".db", ".sqlite"}

# Synthetic logical name for a multipart dataset that spans a directory. The
# directory holds no such file; the id names the dataset, and ``source_paths``
# carries the real parts.
_ALL_PARTS_NAME = "all-parts.parquet"


@dataclass(frozen=True)
class DatasetLoader:
    """A named function that turns one dataset root into browsable records."""

    name: str
    load: Callable[[Path], list[ArtifactSummary]]


def _relative(root: Path, path: Path) -> str:
    """Return a path relative to the artifacts root, in posix form."""
    try:
        return path.resolve().relative_to(Path(root).resolve()).as_posix()
    except ValueError as exc:
        raise DatasetError(f"path is outside the artifacts root: {path}") from exc


def _mtime_ns(path: Path) -> int:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return 0


def _stat_revision(paths: tuple[Path, ...]) -> str:
    """A size+mtime token for a file that is not yet published."""
    return f"{sum(file_size(item) for item in paths)}:{_mtime_ns(paths[0])}"


def _fmt_for(path: Path) -> str:
    return "sqlite" if path.suffix.lower() in {".db", ".sqlite"} else "parquet"


def _read_manifest(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DatasetError(f"unreadable manifest {path}: {exc}") from exc


def _summary(
    root: Path,
    *,
    path: Path,
    kind: str,
    phase: str,
    source_paths: tuple[Path, ...] | None = None,
    revision: str | None = None,
    fmt: str = "parquet",
    run_id: str | None = None,
    table: str | None = None,
) -> ArtifactSummary:
    """Assemble one record, measuring the parts it is built from.

    ``size_bytes`` and ``mtime`` describe the parts on disk rather than the
    logical dataset, so the sidebar reports what is actually occupying space.
    A declared part that is absent is an error, not a smaller dataset.
    """
    parts = tuple(source_paths) if source_paths else (path,)
    missing = [item for item in parts if not item.is_file()]
    if missing:
        raise DatasetError(f"declared part is absent: {missing[0]}")
    return ArtifactSummary(
        id=artifact_id(_relative(root, path), table),
        relative_path=_relative(root, path),
        phase=phase,
        run_id=run_id,
        kind=kind,
        format=fmt,
        size_bytes=sum(file_size(item) for item in parts),
        mtime=newest_mtime(parts),
        revision=revision or _stat_revision(parts),
        source_paths=tuple(_relative(root, item) for item in parts),
        table=table,
    )


# --- metadata (Phase 1) ----------------------------------------------------


def load_metadata(root: Path) -> list[ArtifactSummary]:
    """Phase 1 submissions snapshots, plus each snapshot's CIK index.

    Resolution goes through ``read_snapshot_parts``, so a legacy single-file
    snapshot and a multipart one resolve through one code path. That reader
    verifies every declared digest, so a tampered part raises here and the
    snapshot is left out rather than shown with contents that do not match what
    was published.
    """
    paths = MetadataPaths(artifacts_root=Path(root))
    snapshots_root = paths.snapshots_root
    if not snapshots_root.is_dir():
        return []
    found: list[ArtifactSummary] = []
    for entry in sorted(snapshots_root.iterdir()):
        manifest_path = entry / METADATA_MANIFEST_NAME
        if not manifest_path.is_file():
            continue
        snapshot_id = entry.name
        try:
            revision = manifest_revision(manifest_path)
            plan_id = str(_read_manifest(manifest_path).get("plan_id") or "") or None
        except (OSError, ValueError) as exc:
            # An unreadable manifest means the snapshot is not browsable at all.
            log.warning("skipping metadata snapshot %s: %s", snapshot_id, exc)
            continue

        # The payload and the CIK index are verified independently. A corrupted
        # payload must not hide the index, which carries its own digest and is
        # still a truthful account of what the snapshot claims to cover. The
        # listing shows one record per dataset, so an operator sees the payload
        # missing rather than seeing nothing at all.
        try:
            parts = read_snapshot_parts(manifest_path)
            found.append(
                _summary(
                    root,
                    # A synthetic logical name, not the manifest path. The
                    # manifest is also listed as a browsable *document*, so
                    # reusing its path would give one opaque id two meanings and
                    # make the datasets and documents listings alias each other.
                    path=entry / _ALL_PARTS_NAME,
                    kind="metadata_snapshot",
                    phase=METADATA_DIR,
                    run_id=plan_id,
                    revision=revision,
                    source_paths=parts.paths,
                )
            )
        except (SnapshotLayoutError, DatasetError, OSError, ValueError) as exc:
            log.warning("skipping metadata payload %s: %s", snapshot_id, exc)

        index_path = paths.snapshot_cik_index(snapshot_id)
        if index_path.is_file():
            found.append(
                _summary(
                    root,
                    path=index_path,
                    kind="metadata_cik_index",
                    phase=METADATA_DIR,
                    run_id=plan_id,
                    revision=revision,
                    source_paths=(index_path,),
                )
            )
    return found


# --- filing catalog (Phase 2) ----------------------------------------------


def load_filing_catalog(root: Path) -> list[ArtifactSummary]:
    """Phase 2 catalog snapshots: the profile table and the target shards.

    A catalog is one dataset with two related tables, both browsable. Profiles
    are a single Parquet; targets are sharded, so the shard directory becomes
    one record with a part list rather than a row per shard in the sidebar.
    """
    paths = FilingCatalogPaths(artifacts_root=Path(root))
    catalog_root = paths.snapshots_root
    if not catalog_root.is_dir():
        return []
    found: list[ArtifactSummary] = []
    for entry in sorted(catalog_root.iterdir()):
        manifest_path = entry / CATALOG_MANIFEST_NAME
        if not manifest_path.is_file():
            continue
        try:
            revision = manifest_revision(manifest_path)
        except OSError as exc:
            log.warning("skipping catalog %s: %s", entry.name, exc)
            continue
        profiles = entry / SNAPSHOT_FILE_NAME
        if profiles.is_file():
            found.append(
                _summary(
                    root,
                    path=profiles,
                    kind="catalog_profiles",
                    phase="filing_catalog",
                    revision=revision,
                    source_paths=(profiles,),
                )
            )
        targets_dir = entry / TARGETS_DIR_NAME
        if targets_dir.is_dir():
            target_parts = tuple(sorted(targets_dir.rglob("*.parquet")))
            if target_parts:
                found.append(
                    _summary(
                        root,
                        path=targets_dir / _ALL_PARTS_NAME,
                        kind="catalog_targets",
                        phase="filing_catalog",
                        revision=revision,
                        source_paths=target_parts,
                    )
                )
    return found


# --- document storage (Phase 2.5) -----------------------------------------


def load_document_storage(root: Path) -> list[ArtifactSummary]:
    """Phase 2.5 document snapshots, split by the kind of part they hold.

    A document snapshot stores an ``index`` part (the tabular, browseable view)
    and a ``payload`` part (raw bytes, including the zstd-compressed
    ``raw_payload`` column). They are different shapes of data, so they are
    separate records: browsing raw payload blobs as a table is not useful, and
    the index without its payload would not describe the snapshot.

    Parts are resolved through ``SnapshotReader``, never by globbing, so a
    snapshot that was not fully published is reported rather than partially
    shown.
    """
    snapshots_root = Path(root) / "document_storage" / "snapshots"
    if not snapshots_root.is_dir():
        return []
    found: list[ArtifactSummary] = []
    for entry in sorted(snapshots_root.iterdir()):
        manifest_path = entry / "manifest.json"
        if not manifest_path.is_file():
            continue
        snapshot_id = entry.name
        try:
            reader = SnapshotReader(
                snapshots_root=snapshots_root, snapshot_id=snapshot_id
            )
            revision = manifest_revision(manifest_path)
            run_id = str(reader.manifest.get("run_id") or "") or None
            for kind, label in (
                (PART_KIND_INDEX, "document_index"),
                (PART_KIND_PAYLOAD, "document_payload"),
            ):
                parts = resolved_parts(reader.manifest, kind)
                if not parts:
                    continue
                found.append(
                    _summary(
                        root,
                        path=entry / kind,
                        kind=label,
                        phase="document_storage",
                        run_id=run_id,
                        revision=revision,
                        source_paths=tuple(reader.part_path(part) for part in parts),
                    )
                )
        except (DatasetError, ValueError, OSError) as exc:
            log.warning("skipping document snapshot %s: %s", snapshot_id, exc)
            continue
    return found


# --- transient runs --------------------------------------------------------


def load_transient_runs(root: Path) -> list[ArtifactSummary]:
    """Group unpublished chunk files into one browsable record per run.

    A run in progress has no manifest, so the loaders above cannot resolve it. An
    operator still wants to watch it fill, so chunks sharing a run directory are
    unioned into one record instead of listed one per file.

    The revision for these is a stat-based composite, not a manifest digest: the
    whole point of a union is that it changes as files arrive, and there is no
    manifest yet to hash.
    """
    found: list[ArtifactSummary] = []
    transient_root = Path(root) / "transient"
    if not transient_root.is_dir():
        return found
    for dataset in _TRANSIENT_DATASETS:
        runs_root = transient_root / dataset / "runs"
        if not runs_root.is_dir():
            continue
        for run_dir in sorted(item for item in runs_root.iterdir() if item.is_dir()):
            chunks = tuple(
                path
                for path in walk_files(run_dir)
                if path.suffix.lower() in _DATA_SUFFIXES
            )
            if not chunks:
                continue
            if len(chunks) == 1:
                found.append(
                    _summary(
                        root,
                        path=chunks[0],
                        kind=f"{dataset}_chunk",
                        phase=dataset,
                        run_id=run_dir.name,
                        source_paths=(chunks[0],),
                    )
                )
                continue
            per_file = [
                ArtifactSummary(
                    id="",
                    relative_path=_relative(root, path),
                    phase=dataset,
                    run_id=run_dir.name,
                    kind="chunk",
                    format=_fmt_for(path),
                    size_bytes=file_size(path),
                    mtime=mtime_iso(path),
                    revision=f"{file_size(path)}:{_mtime_ns(path)}",
                )
                for path in chunks
            ]
            synthetic = run_dir / "all-chunks.parquet"
            found.append(
                ArtifactSummary(
                    id=artifact_id(_relative(root, synthetic)),
                    relative_path=_relative(root, synthetic),
                    phase=dataset,
                    run_id=run_dir.name,
                    kind=f"{dataset}_run_union",
                    format=_fmt_for(chunks[0]),
                    size_bytes=sum(file_size(path) for path in chunks),
                    mtime=newest_mtime(chunks),
                    revision=compute_union_revision(per_file),
                    source_paths=tuple(_relative(root, path) for path in chunks),
                )
            )
    return found


# --- sqlite ----------------------------------------------------------------


def _sqlite_tables(path: Path) -> list[str]:
    """List user tables in a SQLite database, best effort.

    The connection comes from the shared ``infra.storage.duckdb`` factory rather
    than ``duckdb.connect``: AGENTS.md §2 requires every connection to carry the
    cgroup-aware resource budget, and the shared factory is the only sanctioned
    seam for it. It opens an in-memory database, which is what table listing
    needs.
    """
    from edgar_sec.infra.storage.duckdb import connect

    try:
        resolved = str(path.resolve()).replace("'", "''")
        conn = connect()
        try:
            rows = conn.execute(
                f"SELECT name FROM sqlite_scan('{resolved}', 'sqlite_master') "
                f"WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name;"
            ).fetchall()
        finally:
            conn.close()
        return [str(row[0]) for row in rows]
    except Exception:  # noqa: BLE001 - listing is best effort by design
        return []


def load_sqlite_databases(root: Path) -> list[ArtifactSummary]:
    """Expose SQLite databases as one record per table.

    The payload store and the transient chunk writer both use SQLite, and an
    operator debugging a failed fetch will want to look inside. Each table is a
    separate record because one database can hold several unrelated shapes and a
    single DuckDB relation can only expose one.
    """
    found: list[ArtifactSummary] = []
    for path in walk_files(Path(root)):
        if path.suffix.lower() not in {".db", ".sqlite"}:
            continue
        for table in _sqlite_tables(path) or ["sqlite_master"]:
            found.append(
                _summary(
                    root,
                    path=path,
                    kind="sqlite_table",
                    phase="sqlite",
                    fmt="sqlite",
                    source_paths=(path,),
                    table=table,
                )
            )
    return found


LOADERS: tuple[DatasetLoader, ...] = (
    DatasetLoader("metadata", load_metadata),
    DatasetLoader("filing_catalog", load_filing_catalog),
    DatasetLoader("document_storage", load_document_storage),
    DatasetLoader("sqlite", load_sqlite_databases),
    DatasetLoader("transient", load_transient_runs),
)


def run_all(root: Path, *, include_sqlite: bool = True) -> list[ArtifactSummary]:
    """Run every loader over ``root`` and return the combined listing.

    A loader that raises is logged and skipped rather than failing the whole
    listing: one damaged dataset should not hide the healthy ones. That is the
    same stance ``list_snapshots`` takes in ``infra.storage.manifests``.
    """
    combined: list[ArtifactSummary] = []
    for loader in LOADERS:
        if not include_sqlite and loader.name == "sqlite":
            continue
        try:
            loaded = loader.load(Path(root))
            if not include_sqlite:
                loaded = [item for item in loaded if item.format != "sqlite"]
            combined.extend(loaded)
        except (DatasetError, OSError, ValueError) as exc:
            log.warning("loader %s failed: %s", loader.name, exc)
    combined.sort(
        key=lambda item: (
            item.phase or "",
            item.run_id or "",
            item.kind,
            item.relative_path,
        )
    )
    return combined


def iter_documents(root: Path) -> list[ArtifactSummary]:
    """List published JSON manifests, browsable as raw text.

    Documents are not tables, so they are a separate listing rather than rows in
    the dataset sidebar. Only files the pipeline layout actually produces are
    considered; the walk does not guess at JSON that happens to be lying around.
    """
    found: list[ArtifactSummary] = []
    seen: set[Path] = set()
    metadata_paths = MetadataPaths(artifacts_root=Path(root))
    candidates: list[Path] = sorted(
        metadata_paths.snapshots_root.glob(f"*/{METADATA_MANIFEST_NAME}")
    )
    catalog_paths = FilingCatalogPaths(artifacts_root=Path(root))
    candidates.extend(
        sorted(catalog_paths.snapshots_root.glob(f"*/{CATALOG_MANIFEST_NAME}"))
    )
    for path in candidates:
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        found.append(
            _summary(
                root,
                path=path,
                kind="manifest",
                phase=METADATA_DIR,
                fmt="json",
                source_paths=(path,),
            )
        )
    found.sort(key=lambda item: item.relative_path)
    return found
