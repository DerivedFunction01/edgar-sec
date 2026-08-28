"""Portable immutable handoff manifests and finalized-artifact bundles."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import zipfile
from collections.abc import Sequence
from pathlib import Path, PurePosixPath
from typing import Any

from defs.storage.artifacts import file_sha256

MANIFEST_VERSION = "1.0.0"
MANIFEST_DIR = "manifests"


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


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
    return hashlib.sha256(_canonical(payload).encode()).hexdigest()[:32]


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


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    try:
        temporary.write_text(_canonical(value) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def publish_manifest(manifest: dict, *, artifacts_root: str) -> Path:
    """Publish adjacent and structured immutable copies of one manifest."""
    validate_manifest(manifest)
    root = Path(artifacts_root).resolve()
    artifact = root / manifest["artifact_path"]
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
            existing = json.loads(path.read_text(encoding="utf-8"))
            stable = ("artifact_id", "artifact_sha256", "dataset", "schema_version")
            if any(existing.get(key) != manifest.get(key) for key in stable):
                raise ValueError(f"conflicting immutable manifest: {path}")
        else:
            _atomic_json(path, manifest)
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
    value = json.loads(Path(path).read_text(encoding="utf-8"))
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
    if path.is_file():
        manifest = load_manifest(path)
    else:
        # Search structured manifests by artifact_id
        candidates = list((root / MANIFEST_DIR).glob(f"**/{path_or_id}.json"))
        if not candidates:
            raise FileNotFoundError(f"manifest not found for artifact id: {path_or_id}")
        manifest = load_manifest(candidates[0])
    artifact = root / manifest["artifact_path"]
    if file_sha256(str(artifact)) != manifest["artifact_sha256"]:
        raise ValueError("artifact hash does not match its manifest")
    return manifest, artifact


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
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            manifest_path.write_text(_canonical(manifest) + "\n", encoding="utf-8")
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
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                os.replace(source, target)
            publish_manifest(manifest, artifacts_root=str(root))
        return [manifest["artifact_id"] for manifest in loaded]


__all__ = [
    "MANIFEST_DIR",
    "artifact_id",
    "create_bundle",
    "find_manifests",
    "import_bundle",
    "load_manifest",
    "make_manifest",
    "manifest_relative_path",
    "prepare_bundle_for_phase",
    "publish_manifest",
    "relative_path",
    "resolve_dependencies",
    "resolve_manifest",
    "resolve_source",
    "validate_manifest",
]
