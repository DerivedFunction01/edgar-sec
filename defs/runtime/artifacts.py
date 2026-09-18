"""Portable immutable handoff manifests and finalized-artifact bundles."""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import subprocess
import tempfile
import zipfile
from collections.abc import Sequence
from pathlib import Path, PurePosixPath
from typing import Any

from defs.storage import (
    atomic_write_json,
    canonical_json,
    file_sha256,
    load_json,
)

logger = logging.getLogger("defs.runtime.artifacts")

MANIFEST_VERSION = "1.0.0"
MANIFEST_DIR = "manifests"


def _relative(path: str | os.PathLike[str], root: str | os.PathLike[str]) -> str:
    value = Path(path).resolve()
    base = Path(root).resolve()
    try:
        result = value.relative_to(base).as_posix()
    except ValueError as exc:
        raise ValueError("artifact path must be inside the artifacts root") from exc
    if result.startswith("../") or result == "..":
        raise ValueError("artifact path may not escape the artifacts root")
    return result


def artifact_id(
    *,
    dataset: str,
    phase: str,
    schema_version: str,
    artifact_sha256: str,
    partition: str = "",
) -> str:
    payload = [
        "artifact-manifest-v1",
        dataset,
        phase,
        schema_version,
        artifact_sha256,
        partition,
    ]
    return hashlib.sha256(canonical_json(payload).encode()).hexdigest()[:32]


def manifest_relative_path(
    *,
    phase: str,
    dataset: str,
    artifact_id_value: str,
    partition: str = "",
) -> str:
    scope_dir = (
        f"partitions/{partition}" if partition and partition != "final" else "final"
    )
    return f"{MANIFEST_DIR}/{phase}/{dataset}/{scope_dir}/{artifact_id_value}.json"


def make_manifest(
    *,
    dataset: str,
    phase: str,
    run_id: str,
    schema_version: str,
    artifact_path: str,
    artifacts_root: str,
    row_count: int,
    byte_count: int | None = None,
    partition: str = "",
    upstream: tuple[str, ...] = (),
    coverage: dict | None = None,
    provenance: dict | None = None,
) -> dict:
    relative = _relative(artifact_path, artifacts_root)
    digest = file_sha256(artifact_path)
    manifest = {
        "manifest_schema_version": MANIFEST_VERSION,
        "artifact_id": artifact_id(
            dataset=dataset,
            phase=phase,
            schema_version=schema_version,
            artifact_sha256=digest,
            partition=partition,
        ),
        "dataset": dataset,
        "producer_phase": phase,
        "run_id": run_id,
        "schema_version": schema_version,
        "artifact_path": relative,
        "storage_format": Path(artifact_path).suffix.lstrip("."),
        "byte_count": byte_count
        if byte_count is not None
        else os.path.getsize(artifact_path),
        "artifact_sha256": digest,
        "row_count": int(row_count),
        "partition": partition,
        "coverage": coverage or {},
        "upstream_artifact_ids": list(upstream),
        "provenance": provenance or {},
    }
    return manifest


def publish_manifest(
    manifest: dict, *, artifacts_root: str, allow_overwrite_adjacent: bool = True
) -> Path:
    """Publish adjacent and structured immutable copies of one manifest."""
    validate_manifest(manifest)
    root = Path(artifacts_root).resolve()
    artifact = root / manifest["artifact_path"]
    if not PurePosixPath(manifest["artifact_path"]).parts[:1] == (MANIFEST_DIR,):
        raise ValueError("published manifests must reference manifests/ artifacts")
    if not artifact.is_file():
        raise FileNotFoundError(f"published artifact does not exist: {artifact}")
    adjacent = artifact.with_name(artifact.name + ".manifest.json")
    rel_path = manifest_relative_path(
        phase=manifest["producer_phase"],
        dataset=manifest["dataset"],
        artifact_id_value=manifest["artifact_id"],
        partition=manifest.get("partition", ""),
    )
    shared = root / rel_path
    paths_to_write = (
        (shared,) if adjacent.parent == shared.parent else (adjacent, shared)
    )
    for path in paths_to_write:
        if path.exists():
            existing = load_json(path)
            stable = ("artifact_id", "artifact_sha256", "dataset", "schema_version")
            if any(existing.get(key) != manifest.get(key) for key in stable):
                if path == adjacent and allow_overwrite_adjacent:
                    atomic_write_json(path, manifest, indent=None)
                else:
                    raise ValueError(f"conflicting immutable manifest: {path}")
        else:
            atomic_write_json(path, manifest, indent=None)
    return shared


def validate_manifest(manifest: dict) -> None:
    required = {
        "manifest_schema_version",
        "artifact_id",
        "dataset",
        "artifact_path",
        "artifact_sha256",
        "storage_format",
        "row_count",
    }
    missing = sorted(required - manifest.keys())
    if missing:
        raise ValueError(f"manifest missing fields: {missing}")
    path = PurePosixPath(manifest["artifact_path"])
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("manifest artifact_path must be relative and contained")
    if manifest["storage_format"] != "parquet":
        raise ValueError("handoff artifacts must be Parquet")


def load_manifest(path: str | os.PathLike[str]) -> dict:
    value = load_json(path)
    validate_manifest(value)
    return value


def find_manifests(
    dataset: str,
    *,
    phase: str | None = None,
    scope: str = "final",
    partition: str = "",
    artifacts_root: str,
) -> list[dict]:
    """Discover immutable manifests for a dataset in structured storage."""
    root = Path(artifacts_root).resolve()
    manifests_root = root / MANIFEST_DIR
    if not manifests_root.exists():
        return []
    scope_dir = (
        f"partitions/{partition}" if partition and partition != "final" else "final"
    )
    pattern = (
        f"{phase}/{dataset}/{scope_dir}/*.json"
        if phase
        else f"*/{dataset}/{scope_dir}/*.json"
    )
    discovered = []
    seen_ids: set[str] = set()
    for manifest_path in sorted(manifests_root.glob(pattern)):
        try:
            manifest = load_manifest(manifest_path)
            aid = manifest["artifact_id"]
            if aid in seen_ids:
                continue
            artifact = root / manifest["artifact_path"]
            if (
                artifact.is_file()
                and file_sha256(str(artifact)) == manifest["artifact_sha256"]
            ):
                discovered.append(manifest)
                seen_ids.add(aid)
        except (OSError, ValueError):
            continue
    return discovered


def resolve_manifest(
    path_or_id: str | os.PathLike[str], *, artifacts_root: str
) -> tuple[dict, Path]:
    """Resolve an artifact manifest and verify its artifact content hash."""
    root = Path(artifacts_root).resolve()
    path = Path(path_or_id)
    if not path.is_file():
        # Search structured manifests by artifact_id or snapshot_id
        candidates = list((root / MANIFEST_DIR).glob(f"**/{path_or_id}.json"))
        if not candidates:
            candidates = list(
                (root / MANIFEST_DIR).glob(f"**/snapshots/{path_or_id}/*.manifest.json")
            )
        if not candidates:
            raise FileNotFoundError(f"manifest not found for artifact id: {path_or_id}")
        path = candidates[0]
    raw = load_json(path)
    if "snapshot_id" in raw:
        validate_snapshot_manifest(raw)
        return raw, path
    validate_manifest(raw)
    artifact = root / raw["artifact_path"]
    if file_sha256(str(artifact)) != raw["artifact_sha256"]:
        raise ValueError("artifact hash does not match its manifest")
    return raw, artifact


def resolve_source(
    dataset: str,
    *,
    phase: str | None = None,
    partition_id: int | str | None = None,
    artifacts_root: str | os.PathLike[str] | None = None,
) -> tuple[list[dict], list[Path]]:
    """Resolve source dataset artifacts by checking final manifests first, then partitions.

    Returns:
        tuple of (list of manifests, list of verified artifact Paths)
    """
    from defs.runtime.paths import resolve_paths

    root = (
        Path(artifacts_root).resolve()
        if artifacts_root is not None
        else resolve_paths().artifacts_root
    )
    if partition_id is not None:
        part_str = (
            f"partition-{partition_id:05d}"
            if isinstance(partition_id, int)
            else str(partition_id)
        )
        manifests = find_manifests(
            dataset,
            phase=phase,
            scope="partition",
            partition=part_str,
            artifacts_root=str(root),
        )
        if not manifests:
            raise FileNotFoundError(
                f"No published partition manifest found for dataset {dataset!r} "
                f"({part_str}) under {root}"
            )
        paths = [root / m["artifact_path"] for m in manifests]
        return manifests, paths

    # Try final manifest first
    final_manifests = find_manifests(
        dataset, phase=phase, scope="final", artifacts_root=str(root)
    )
    if final_manifests:
        return final_manifests, [root / final_manifests[0]["artifact_path"]]

    # Fallback to partition manifests
    partition_manifests = find_manifests(
        dataset, phase=phase, scope="partition", partition="*", artifacts_root=str(root)
    )
    if partition_manifests:
        return partition_manifests, [
            root / m["artifact_path"] for m in partition_manifests
        ]

    raise FileNotFoundError(
        f"No published manifest found for dataset {dataset!r}"
        + (f" from phase {phase!r}" if phase else "")
        + f" under {root}. Ensure upstream merge has completed or import an artifact bundle."
    )


def resolve_dependencies(
    dependencies: Sequence[Any],
    *,
    artifacts_root: str | os.PathLike[str] | None = None,
) -> list[dict]:
    """Resolve manifests for all declared phase dependencies."""
    from defs.runtime.paths import resolve_paths

    root = (
        Path(artifacts_root).resolve()
        if artifacts_root is not None
        else resolve_paths().artifacts_root
    )
    resolved_manifests: list[dict] = []
    missing_deps: list[str] = []
    for dep in dependencies:
        phase = getattr(dep, "phase", None) or (
            dep.get("phase") if isinstance(dep, dict) else None
        )
        dataset = getattr(dep, "dataset", None) or (
            dep.get("dataset") if isinstance(dep, dict) else None
        )
        required = (
            getattr(dep, "required", True)
            if hasattr(dep, "required")
            else (dep.get("required", True) if isinstance(dep, dict) else True)
        )
        try:
            manifests, _ = resolve_source(
                dataset, phase=phase, artifacts_root=str(root)
            )
            resolved_manifests.extend(manifests)
        except FileNotFoundError:
            if required:
                missing_deps.append(f"{phase}/{dataset}")
    if missing_deps:
        raise FileNotFoundError(
            f"Missing required upstream dependencies under {root}: {', '.join(missing_deps)}. "
            "Ensure upstream phases have completed or import their artifact bundles."
        )
    return resolved_manifests


def prepare_bundle_for_phase(
    target_phase: str,
    *,
    output: str,
    artifacts_root: str | os.PathLike[str] | None = None,
) -> tuple[str, list[dict]]:
    """Resolve declared upstream dependencies for a phase and export them as a bundle."""
    from defs.runtime.paths import resolve_paths
    from defs.runtime.registry import get_phase_dependencies

    root = (
        Path(artifacts_root).resolve()
        if artifacts_root is not None
        else resolve_paths().artifacts_root
    )
    deps = get_phase_dependencies(target_phase)
    if not deps:
        raise ValueError(
            f"No upstream dependencies declared for phase: {target_phase!r}"
        )
    manifests = resolve_dependencies(deps, artifacts_root=str(root))
    artifact_ids = [m["artifact_id"] for m in manifests]
    create_bundle(artifact_ids, artifacts_root=str(root), output=output)
    return output, manifests


def relative_path(path: str | os.PathLike[str], root: str | os.PathLike[str]) -> str:
    """Return a portable path relative to an artifact root."""
    return _relative(path, root)


def create_bundle(
    artifact_ids: list[str],
    *,
    artifacts_root: str,
    output: str,
    trust_manifests: bool = False,
) -> None:
    root = Path(artifacts_root).resolve()
    manifests: dict[str, dict] = {}
    pending = list(artifact_ids)
    while pending:
        current = pending.pop()
        if current in manifests:
            continue
        manifest, path = resolve_manifest(current, artifacts_root=str(root))
        if not path.is_file():
            raise FileNotFoundError(path)
        manifests[current] = manifest
        pending.extend(manifest.get("upstream_artifact_ids", ()))
    output_path = Path(output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output_path.parent) as temporary:
        staging = Path(temporary)
        for key, manifest in manifests.items():
            manifest_path = staging / "manifests" / f"{key}.json"
            atomic_write_json(manifest_path, manifest, indent=None)
        included: set[str] = set()
        for manifest in manifests.values():
            relative = manifest["artifact_path"]
            if relative not in included:
                target = staging / "artifacts" / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                _link_or_copy(root / relative, target)
                included.add(relative)
        try:
            _create_with_native_tool(staging, output_path)
        except FileNotFoundError:
            with zipfile.ZipFile(
                output_path, "w", compression=zipfile.ZIP_STORED
            ) as archive:
                for path in staging.rglob("*"):
                    if path.is_file():
                        archive.write(path, path.relative_to(staging).as_posix())


def _archive_tool(*names: str) -> tuple[str, str]:
    for name in names:
        executable = shutil.which(name)
        if executable is not None:
            return executable, name
    raise FileNotFoundError(
        "No supported archive tool found. Install 7z, zip, or unzip."
    )


def _create_with_native_tool(source_dir: Path, archive_path: Path) -> None:
    executable, tool_name = _archive_tool("7z", "7za", "zip")
    if tool_name in {"7z", "7za"}:
        command = [executable, "a", "-tzip", "-mx=0", "-y", str(archive_path), "."]
    else:
        command = [executable, "-q", "-0", "-r", str(archive_path), "."]
    subprocess.run(
        command,
        check=True,
        cwd=source_dir,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _link_or_copy(source: Path, target: Path) -> None:
    try:
        os.link(source, target)
    except OSError:
        shutil.copyfile(source, target)


def _archive_extractor() -> tuple[str, str]:
    return _archive_tool("7z", "7za", "unzip")


def _extract_with_native_tool(archive_path: Path, destination_dir: Path) -> None:
    executable, tool_name = _archive_extractor()
    destination_dir.mkdir(parents=True, exist_ok=True)
    if tool_name in {"7z", "7za"}:
        command = [executable, "x", "-y", f"-o{destination_dir}", str(archive_path)]
    else:
        command = [executable, "-o", str(archive_path), "-d", str(destination_dir)]
    subprocess.run(
        command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )


def import_bundle(
    bundle: str, *, artifacts_root: str, verify_hash: bool = True
) -> list[str]:
    root = Path(artifacts_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root.parent) as temporary:
        stage = Path(temporary)
        try:
            _extract_with_native_tool(Path(bundle).resolve(), stage)
        except FileNotFoundError:
            # Keep the library usable on minimal Python-only environments.
            with zipfile.ZipFile(bundle) as archive:
                archive.extractall(stage)
        if any(
            path.relative_to(stage).parts[0] not in {"manifests", "artifacts"}
            for path in stage.rglob("*")
            if path.is_file()
        ):
            raise ValueError("bundle contains files outside manifests/ or artifacts/")
        manifest_paths = sorted((stage / "manifests").glob("*.json"))
        loaded = []
        for path in manifest_paths:
            manifest = load_manifest(path)
            file = stage / "artifacts" / manifest["artifact_path"]
            if verify_hash and file_sha256(str(file)) != manifest["artifact_sha256"]:
                raise ValueError(f"bundle hash mismatch: {path.name}")
            loaded.append(manifest)
        for manifest in loaded:
            target = root / manifest["artifact_path"]
            source = stage / "artifacts" / manifest["artifact_path"]
            if (
                target.exists()
                and file_sha256(str(target)) != manifest["artifact_sha256"]
            ):
                raise ValueError(f"import conflicts with existing artifact: {target}")
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(source, target)
            publish_manifest(manifest, artifacts_root=str(root))
        return [manifest["artifact_id"] for manifest in loaded]


def make_snapshot_manifest(
    *,
    snapshot_id: str,
    schema_version: str,
    resolved_parts: list[dict],
    added_parts: list[dict] | None = None,
    replacement_key_parts: list[dict] | None = None,
    parent_snapshot_id: str | None = None,
    source_snapshot_ids: list[str] | None = None,
    plan_id: str | None = None,
    effective_cik_count: int | None = None,
    effective_input_fingerprint: str | None = None,
    dataset: str = "submission_metadata",
    phase: str = "metadata",
    validation_status: str = "ok",
    provenance: dict | None = None,
) -> dict:
    """Create a structured multi-part snapshot manifest dictionary."""
    total_rows = (
        effective_cik_count
        if effective_cik_count is not None
        else sum(int(p.get("row_count", 0)) for p in resolved_parts)
    )
    manifest = {
        "manifest_kind": f"{dataset}_snapshot",
        "manifest_schema_version": MANIFEST_VERSION,
        "dataset": dataset,
        "producer_phase": phase,
        "snapshot_id": snapshot_id,
        "parent_snapshot_id": parent_snapshot_id,
        "schema_version": schema_version,
        "resolved_parts": resolved_parts,
        "added_parts": added_parts or [],
        "replacement_key_parts": replacement_key_parts or [],
        "source_snapshot_ids": source_snapshot_ids or [],
        "plan_id": plan_id,
        "effective_cik_count": total_rows,
        "row_count": total_rows,
        "effective_input_fingerprint": effective_input_fingerprint,
        "validation_status": validation_status,
        "provenance": provenance or {},
    }
    return manifest


def validate_snapshot_manifest(manifest: dict) -> None:
    """Validate a multi-part snapshot manifest."""
    if not isinstance(manifest, dict):
        raise ValueError("snapshot manifest must be a dictionary")
    kind = manifest.get("manifest_kind", "")
    if not kind.endswith("_snapshot") and kind != "submission_metadata_snapshot":
        raise ValueError(f"invalid manifest_kind for snapshot: {kind}")
    required = {
        "manifest_kind",
        "manifest_schema_version",
        "snapshot_id",
        "schema_version",
        "resolved_parts",
    }
    missing = sorted(required - manifest.keys())
    if missing:
        raise ValueError(f"snapshot manifest missing fields: {missing}")
    if not isinstance(manifest.get("resolved_parts"), list):
        raise ValueError("snapshot manifest resolved_parts must be a list")
    for part in manifest["resolved_parts"]:
        if (
            not isinstance(part, dict)
            or "path" not in part
            or "artifact_sha256" not in part
        ):
            raise ValueError("each resolved part must specify path and artifact_sha256")


def publish_snapshot_manifest(
    manifest: dict,
    *,
    artifacts_root: str | os.PathLike[str],
    phase: str = "metadata",
    dataset: str = "submission_metadata",
    set_current: bool = True,
) -> Path:
    """Write snapshot manifest atomically to its canonical path and update pointer if requested."""
    validate_snapshot_manifest(manifest)
    from defs.runtime.paths import resolve_paths

    phase_name = manifest.get("producer_phase", phase)
    dataset_name = manifest.get("dataset", dataset)
    paths = resolve_paths(env={"ARTIFACTS_ROOT": str(artifacts_root)})
    snapshot_id = manifest["snapshot_id"]
    manifest_path = paths.dataset_snapshot_manifest_path(
        phase_name, dataset_name, snapshot_id
    )
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    if manifest_path.exists():
        existing = load_json(manifest_path)
        if existing.get("snapshot_id") != snapshot_id or existing.get(
            "resolved_parts"
        ) != manifest.get("resolved_parts"):
            raise ValueError(
                f"conflicting immutable snapshot manifest: {manifest_path}"
            )
    else:
        atomic_write_json(manifest_path, manifest, indent=2, sort_keys=True)
    if set_current:
        update_current_snapshot_pointer(
            snapshot_id,
            manifest_path=manifest_path,
            phase=phase_name,
            dataset=dataset_name,
            artifacts_root=artifacts_root,
        )
    return manifest_path


def update_current_snapshot_pointer(
    snapshot_id: str,
    *,
    manifest_path: str | os.PathLike[str] | None = None,
    phase: str = "metadata",
    dataset: str = "submission_metadata",
    artifacts_root: str | os.PathLike[str],
) -> Path:
    """Atomically advance or roll back the current dataset snapshot pointer."""
    from defs.runtime.paths import resolve_paths

    paths = resolve_paths(env={"ARTIFACTS_ROOT": str(artifacts_root)})
    pointer_path = paths.dataset_current_pointer_path(phase, dataset)
    pointer_path.parent.mkdir(parents=True, exist_ok=True)
    root = Path(artifacts_root).resolve()
    rel_path = (
        _relative(manifest_path, root)
        if manifest_path is not None
        else _relative(
            paths.dataset_snapshot_manifest_path(phase, dataset, snapshot_id), root
        )
    )
    payload = {
        "pointer_kind": f"{dataset}_current_snapshot",
        "dataset": dataset,
        "producer_phase": phase,
        "snapshot_id": snapshot_id,
        "manifest_path": rel_path,
    }
    atomic_write_json(pointer_path, payload, indent=2, sort_keys=True)
    return pointer_path


def get_current_snapshot_pointer(
    artifacts_root: str | os.PathLike[str],
    *,
    phase: str = "metadata",
    dataset: str = "submission_metadata",
) -> dict | None:
    """Get the current dataset snapshot pointer dict, or None if not set."""
    from defs.runtime.paths import resolve_paths

    paths = resolve_paths(env={"ARTIFACTS_ROOT": str(artifacts_root)})
    pointer_path = paths.dataset_current_pointer_path(phase, dataset)
    if not pointer_path.exists():
        return None
    try:
        return load_json(pointer_path)
    except (OSError, ValueError):
        return None


def resolve_snapshot_manifest(
    snapshot_id_or_path: str | os.PathLike[str] | None = None,
    *,
    artifacts_root: str | os.PathLike[str],
    phase: str = "metadata",
    dataset: str = "submission_metadata",
) -> tuple[dict, Path]:
    """Resolve a snapshot manifest dict and verify part paths exist and hashes match."""
    from defs.runtime.paths import resolve_paths

    root = Path(artifacts_root).resolve()
    paths = resolve_paths(env={"ARTIFACTS_ROOT": str(root)})
    if snapshot_id_or_path is None:
        pointer = get_current_snapshot_pointer(root, phase=phase, dataset=dataset)
        if pointer is None:
            raise FileNotFoundError(
                f"no current snapshot pointer found for {phase}/{dataset} under {root}"
            )
        snapshot_manifest_file = root / pointer["manifest_path"]
    else:
        path = Path(snapshot_id_or_path)
        if path.is_file():
            snapshot_manifest_file = path
        elif path.is_dir() and (path / "snapshot.manifest.json").is_file():
            snapshot_manifest_file = path / "snapshot.manifest.json"
        elif path.is_dir() and (path / "snapshot.json").is_file():
            snapshot_manifest_file = path / "snapshot.json"
        else:
            snapshot_manifest_file = paths.dataset_snapshot_manifest_path(
                phase, dataset, str(snapshot_id_or_path)
            )
    if not snapshot_manifest_file.is_file():
        raise FileNotFoundError(
            f"snapshot manifest not found: {snapshot_manifest_file}"
        )
    manifest = load_json(snapshot_manifest_file)
    validate_snapshot_manifest(manifest)
    return manifest, snapshot_manifest_file


def list_snapshots(
    *,
    phase: str = "metadata",
    dataset: str = "submission_metadata",
    artifacts_root: str | os.PathLike[str],
) -> list[dict]:
    """Return all available snapshots for a dataset, sorted by snapshot_id / creation."""
    from defs.runtime.paths import resolve_paths

    root = Path(artifacts_root).resolve()
    paths = resolve_paths(env={"ARTIFACTS_ROOT": str(root)})
    snapshots_dir = paths.dataset_snapshots_dir(phase, dataset)
    if not snapshots_dir.is_dir():
        return []

    snapshots: list[dict] = []
    for entry in snapshots_dir.iterdir():
        if not entry.is_dir():
            continue
        manifest_p = entry / "snapshot.manifest.json"
        if not manifest_p.is_file():
            manifest_p = entry / "snapshot.json"
        if manifest_p.is_file():
            try:
                manifest = load_json(manifest_p)
                snapshots.append(
                    {
                        "snapshot_id": manifest.get("snapshot_id", entry.name),
                        "parent_snapshot_id": manifest.get("parent_snapshot_id"),
                        "effective_cik_count": manifest.get(
                            "effective_cik_count", manifest.get("row_count", 0)
                        ),
                        "part_count": len(manifest.get("resolved_parts", [])),
                        "schema_version": manifest.get("schema_version", ""),
                        "manifest_path": str(manifest_p.relative_to(root)),
                        "dir_path": str(entry.relative_to(root)),
                        "manifest": manifest,
                    }
                )
            except (OSError, ValueError, KeyError, TypeError) as exc:
                logger.debug(
                    "skipping invalid snapshot manifest %s: %s", manifest_p, exc
                )
                continue

    def _sort_key(s: dict) -> tuple[int, int, str]:
        sid = s["snapshot_id"]
        if sid.startswith("S") and sid[1:].isdigit():
            return (0, int(sid[1:]), sid)
        return (1, 0, sid)

    snapshots.sort(key=_sort_key)
    return snapshots


def next_snapshot_id(
    *,
    phase: str = "metadata",
    dataset: str = "submission_metadata",
    artifacts_root: str | os.PathLike[str],
) -> str:
    """Determine the next sequential snapshot ID (e.g. S0 -> S1 -> S2)."""
    snapshots = list_snapshots(
        phase=phase, dataset=dataset, artifacts_root=artifacts_root
    )
    if not snapshots:
        return "S0"

    monotonic_indices: list[int] = []
    for s in snapshots:
        sid = s["snapshot_id"]
        if sid.startswith("S") and sid[1:].isdigit():
            monotonic_indices.append(int(sid[1:]))

    if monotonic_indices:
        return f"S{max(monotonic_indices) + 1}"

    return f"S{len(snapshots)}"


__all__ = [
    "MANIFEST_DIR",
    "artifact_id",
    "create_bundle",
    "find_manifests",
    "get_current_snapshot_pointer",
    "import_bundle",
    "list_snapshots",
    "load_manifest",
    "make_manifest",
    "make_snapshot_manifest",
    "manifest_relative_path",
    "next_snapshot_id",
    "prepare_bundle_for_phase",
    "publish_manifest",
    "publish_snapshot_manifest",
    "relative_path",
    "resolve_dependencies",
    "resolve_manifest",
    "resolve_snapshot_manifest",
    "resolve_source",
    "update_current_snapshot_pointer",
    "validate_manifest",
    "validate_snapshot_manifest",
]
