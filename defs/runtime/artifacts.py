"""Portable immutable handoff manifests and finalized-artifact bundles."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

from defs.storage.artifacts import file_sha256

MANIFEST_VERSION = "1.0.0"
MANIFEST_DIR = "artifact-manifests"


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
    """Publish adjacent and shared immutable copies of one manifest."""
    validate_manifest(manifest)
    root = Path(artifacts_root).resolve()
    artifact = root / manifest["artifact_path"]
    # Multiple finalized datasets can share a merge/catalog directory.
    adjacent = artifact.with_name(artifact.name + ".manifest.json")
    shared = root / MANIFEST_DIR / f"{manifest['artifact_id']}.json"
    for path in (adjacent, shared):
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


def resolve_manifest(
    artifact_id_value: str, *, artifacts_root: str
) -> tuple[dict, Path]:
    path = Path(artifacts_root) / MANIFEST_DIR / f"{artifact_id_value}.json"
    manifest = load_manifest(path)
    artifact = Path(artifacts_root).resolve() / manifest["artifact_path"]
    if file_sha256(str(artifact)) != manifest["artifact_sha256"]:
        raise ValueError("artifact hash does not match its manifest")
    return manifest, artifact


def discover_legacy_manifests(
    *, artifacts_root: str, publish: bool = False
) -> list[dict]:
    """Find validated finalized outputs from pre-manifest merge reports."""
    root = Path(artifacts_root).resolve()
    discovered = []
    for report_path in root.glob("**/merge_report.json"):
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
            output = Path(report["output_path"]).resolve()
            output.relative_to(root)
            if any(
                part in {"chunks", "checkpoints", "workers"} for part in output.parts
            ):
                continue
            if output.suffix != ".parquet" or not output.is_file():
                continue
            if file_sha256(str(output)) != report.get("artifact_sha256"):
                continue
            relative = output.relative_to(root).as_posix()
            parts = Path(relative).parts
            phase = parts[0] if parts else "unknown"
            run_id = (
                parts[2]
                if len(parts) > 2 and parts[1] == "runs"
                else report_path.parent.name
            )
            manifest = make_manifest(
                dataset=output.stem,
                phase=phase,
                run_id=run_id,
                schema_version=report.get("schema_version", "unknown"),
                artifact_path=str(output),
                artifacts_root=str(root),
                row_count=int(report.get("row_count", 0)),
                provenance={
                    "legacy_merge_report": report_path.relative_to(root).as_posix(),
                    "report_source": report.get("report_source"),
                },
            )
            discovered.append(manifest)
            if publish:
                publish_manifest(manifest, artifacts_root=str(root))
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            continue
    return discovered


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
        manifest, path = (
            resolve_manifest(current, artifacts_root=str(root))
            if not trust_manifests
            else (
                load_manifest(root / MANIFEST_DIR / f"{current}.json"),
                root
                / load_manifest(root / MANIFEST_DIR / f"{current}.json")[
                    "artifact_path"
                ],
            )
        )
        if not trust_manifests and not path.is_file():
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
    "discover_legacy_manifests",
    "import_bundle",
    "load_manifest",
    "make_manifest",
    "publish_manifest",
    "relative_path",
    "resolve_manifest",
    "validate_manifest",
]
