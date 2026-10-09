"""One loader per published dataset type.

A dataset becomes browsable only when its manifest is present and its declared parts
exist: an in-flight run or a half-published snapshot is reported, never shown as a
shorter dataset.
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
from edgar_sec.apps.viewer.paths import (
    DATA_SUFFIXES,
    DATABASE_SUFFIXES,
)
from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.infra.storage.dag.catalog import DAGCatalog
from edgar_sec.pipelines.document_storage.manifests import (
    PART_KIND_INDEX,
    PART_KIND_PAYLOAD,
    SnapshotReader,
    resolved_parts,
)
from edgar_sec.foundation.runtime.paths import SNAPSHOTS_DIR, TRANSIENT_DIR
from edgar_sec.pipelines.filing_catalog.paths import FilingCatalogPaths
from edgar_sec.pipelines.document_storage.paths import DOCUMENTS_DATASET
from edgar_sec.pipelines.metadata_sync.paths import (
    METADATA_DIR,
    MetadataPaths,
)
from edgar_sec.pipelines.metadata_sync.snapshot import (
    SnapshotCatalogError,
    resolve_snapshot_parts,
)

log = logging.getLogger("apps.viewer.loaders")

__all__ = [
    "LOADERS",
    "DatasetLoader",
    "load_document_storage",
    "load_filing_catalog",
    "load_metadata",
    "load_sqlite_databases",
    "load_transient_runs",
    "run_all",
]

_TRANSIENT_DATASETS = (METADATA_DIR, "filing_catalog", "document_storage")

# Synthetic logical name for a multipart dataset spanning a directory; no such
# file exists. The id names the dataset and ``source_paths`` carries the real parts.
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
    return "sqlite" if path.suffix.lower() in DATABASE_SUFFIXES else "parquet"


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

    Size and mtime describe the parts on disk, so the sidebar reports what occupies
    space. A declared part that is absent is an error, not a smaller dataset.
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


def load_metadata(root: Path) -> list[ArtifactSummary]:
    """Metadata submissions snapshots, plus each snapshot's CIK index.

    Parts and their digests come from the DAG catalog, so a tampered part is left out
    rather than shown with contents that do not match what was published.
    """
    paths = MetadataPaths(artifacts_root=Path(root))
    try:
        catalog = DAGCatalog(paths.snapshots_root, read_only=True)
    except FileNotFoundError:
        return []
    found: list[ArtifactSummary] = []
    for row in catalog.list_snapshots():
        snapshot_id = str(row["snapshot_id"])
        snapshot = catalog.get_manifest(snapshot_id)
        if snapshot is None or "submissions" not in snapshot.relations:
            continue
        try:
            parts = resolve_snapshot_parts(paths, snapshot_id)
            found.append(
                _summary(
                    root,
                    path=paths.snapshot_dir(snapshot_id) / _ALL_PARTS_NAME,
                    kind="metadata_snapshot",
                    phase=METADATA_DIR,
                    run_id=str(snapshot.metadata.get("plan_id") or "") or None,
                    revision=snapshot.manifest_sha256,
                    source_paths=parts.paths,
                )
            )
        except (SnapshotCatalogError, DatasetError, OSError, ValueError) as exc:
            log.warning("skipping metadata payload %s: %s", snapshot_id, exc)

        try:
            index = resolve_snapshot_parts(paths, snapshot_id, "cik_index")
            index_path = index.paths[0]
            found.append(
                _summary(
                    root,
                    path=index_path,
                    kind="metadata_cik_index",
                    phase=METADATA_DIR,
                    run_id=str(snapshot.metadata.get("plan_id") or "") or None,
                    revision=snapshot.manifest_sha256,
                    source_paths=(index_path,),
                )
            )
        except (SnapshotCatalogError, DatasetError, OSError, ValueError) as exc:
            log.warning("skipping metadata CIK index %s: %s", snapshot_id, exc)
    return found


def load_filing_catalog(root: Path) -> list[ArtifactSummary]:
    """Catalog snapshots: the profile table and the target shards.

    One dataset with two browsable tables; the shard directory becomes one record with
    a part list rather than a row per shard.
    """
    paths = FilingCatalogPaths(artifacts_root=Path(root))
    try:
        catalog = DAGCatalog(paths.snapshots_root, read_only=True)
    except FileNotFoundError:
        return []
    found: list[ArtifactSummary] = []
    for row in catalog.list_snapshots():
        snapshot = catalog.get_manifest(str(row["snapshot_id"]))
        if snapshot is None:
            continue
        catalog_id = snapshot.snapshot_id
        if snapshot.relations.get("company_profiles"):
            try:
                profile_paths = catalog.resolve_relation(catalog_id, "company_profiles")
            except ValueError as exc:
                log.warning("skipping catalog profiles %s: %s", catalog_id, exc)
                profile_paths = ()
        else:
            profile_paths = ()
        if profile_paths:
            found.append(
                _summary(
                    root,
                    path=profile_paths[0],
                    kind="catalog_profiles",
                    phase="filing_catalog",
                    revision=snapshot.manifest_sha256,
                    source_paths=profile_paths,
                )
            )
        if snapshot.relations.get("filing_targets"):
            try:
                target_paths = catalog.resolve_relation(catalog_id, "filing_targets")
            except ValueError as exc:
                log.warning("skipping catalog targets %s: %s", catalog_id, exc)
                target_paths = ()
        else:
            target_paths = ()
        if target_paths:
            found.append(
                _summary(
                    root,
                    path=paths.snapshot_dir(catalog_id) / _ALL_PARTS_NAME,
                    kind="catalog_targets",
                    phase="filing_catalog",
                    revision=snapshot.manifest_sha256,
                    source_paths=target_paths,
                )
            )
    return found


def load_document_storage(root: Path) -> list[ArtifactSummary]:
    """Document snapshots, split by the kind of part they hold.

    Index and payload are separate records; parts resolve through ``SnapshotReader``,
    never by globbing, so an unfinished publication is reported, not partially shown.
    """
    snapshots_root = Path(root) / DOCUMENTS_DATASET / SNAPSHOTS_DIR
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


def load_transient_runs(root: Path) -> list[ArtifactSummary]:
    """Group unpublished chunk files into one browsable record per run.

    A run in progress has no manifest for the loaders above to resolve. The revision is
    a stat composite, not a digest, because a union changes as files arrive.
    """
    found: list[ArtifactSummary] = []
    transient_root = Path(root) / TRANSIENT_DIR
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
                if path.suffix.lower() in DATA_SUFFIXES
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

    Uses the shared ``connect`` factory, so the connection carries its budget.
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

    One database can hold unrelated shapes and a single DuckDB relation exposes one.
    """
    found: list[ArtifactSummary] = []
    for path in walk_files(Path(root)):
        if path.suffix.lower() not in DATABASE_SUFFIXES:
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

    A loader that raises is logged and skipped: one damaged dataset must not hide the
    healthy ones.
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
