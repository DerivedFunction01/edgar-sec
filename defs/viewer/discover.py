"""Artifact discovery for the viewer.

Scans the artifacts workspace, classifies every tabular file through the
shared layout contract (``defs.runtime.paths.classify_artifact_path``), and
groups JSON documents separately. Discovery only stats files; content is
read lazily by the dataset layer.
"""

from __future__ import annotations

import base64
import hashlib
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from defs.runtime.paths import ArtifactRole, classify_artifact_path

DOCUMENT_ROLES = frozenset(
    {
        ArtifactRole.RUN_PLAN,
        ArtifactRole.PARTITION_MANIFEST,
        ArtifactRole.MERGE_REPORT,
    }
)

_TABULAR_SUFFIXES = {".parquet": "parquet", ".jsonl": "jsonl"}


@dataclass(frozen=True)
class ArtifactSummary:
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


def compute_revision(size_bytes: int, mtime_ns: int) -> str:
    """Change token for a single artifact: size + nanosecond mtime."""
    return f"{size_bytes}:{mtime_ns}"


def compute_union_revision(items: list[ArtifactSummary]) -> str:
    """Composite change token for a run union.

    Hash of the sorted per-file tokens (relative_path:size:mtime_ns) plus the
    file count, so adding/removing/changing a chunk invalidates the entry.
    """
    tokens = sorted(
        f"{item.relative_path}:{item.revision}" for item in items if item.revision
    )
    digest = hashlib.sha256("|".join(tokens).encode("utf-8")).hexdigest()[:16]
    return f"{digest}:{len(items)}"


def artifact_id(relative_path: str | Path) -> str:
    """URL-safe opaque id for an artifact relative path."""
    posix = Path(relative_path).as_posix()
    return base64.urlsafe_b64encode(posix.encode("utf-8")).decode("ascii")


def artifact_path(artifact_id_value: str, root: Path) -> Path:
    """Resolve an id back to a path, refusing anything outside ``root``."""
    try:
        relative = base64.urlsafe_b64decode(artifact_id_value.encode("ascii")).decode(
            "utf-8"
        )
    except Exception as exc:
        raise ValueError(f"invalid dataset id: {artifact_id_value!r}") from exc
    candidate = (root / relative).resolve()
    root_resolved = root.resolve()
    if candidate != root_resolved and root_resolved not in candidate.parents:
        raise ValueError("dataset path escapes the artifacts root")
    return candidate


def _suffix_format(suffix: str) -> str | None:
    return _TABULAR_SUFFIXES.get(suffix.lower())


def _mtime_iso(stat: os.stat_result) -> str | None:
    from datetime import UTC, datetime

    return (
        datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat()
        if stat.st_mtime > 0
        else None
    )


def _summarize(root: Path, file_path: Path) -> ArtifactSummary | None:
    relative = file_path.relative_to(root)
    classification = classify_artifact_path(relative)
    stat = file_path.stat()
    fmt = _suffix_format(file_path.suffix)
    if fmt is None:
        if (
            classification.role in DOCUMENT_ROLES
            and file_path.suffix.lower() == ".json"
        ):
            fmt = "json"
        else:
            return None
    return ArtifactSummary(
        id=artifact_id(relative),
        relative_path=relative.as_posix(),
        phase=classification.phase,
        run_id=classification.run_id,
        kind=classification.role.value,
        format=fmt,
        size_bytes=stat.st_size,
        mtime=_mtime_iso(stat),
        revision=compute_revision(stat.st_size, stat.st_mtime_ns),
    )


def discover_artifacts(root: Path) -> list[ArtifactSummary]:
    """List every tabular artifact under ``root`` (stat-only, no content reads)."""
    summaries: list[ArtifactSummary] = []
    for current, _dirs, files in os.walk(root):
        for name in files:
            file_path = Path(current) / name
            summary = _summarize(root, file_path)
            if summary is not None and summary.format in {"parquet", "jsonl"}:
                summaries.append(summary)
    unions: list[ArtifactSummary] = []
    grouped: dict[tuple[str, str, str], list[ArtifactSummary]] = {}
    for item in summaries:
        if item.run_id and item.kind in {"partition_chunk", "chunk", "worker_fragment"}:
            grouped.setdefault((item.phase or "", item.run_id, item.format), []).append(
                item
            )
    for (phase, run_id, fmt), items in grouped.items():
        if len(items) < 2:
            continue
        source_paths = tuple(
            item.relative_path for item in sorted(items, key=lambda x: x.relative_path)
        )
        relative = f"{phase}/runs/{run_id}/all-chunks.{fmt}"
        size = sum(item.size_bytes for item in items)
        mtimes = [item.mtime for item in items if item.mtime]
        unions.append(
            ArtifactSummary(
                id=artifact_id(relative),
                relative_path=relative,
                phase=phase,
                run_id=run_id,
                kind="run_union",
                format=fmt,
                size_bytes=size,
                mtime=max(mtimes) if mtimes else None,
                revision=compute_union_revision(items),
                source_paths=source_paths,
            )
        )
    summaries.extend(unions)
    summaries.sort(
        key=lambda item: (
            item.phase or "",
            item.run_id or "",
            item.kind,
            item.relative_path,
        )
    )
    return summaries


def discover_documents(root: Path) -> list[ArtifactSummary]:
    """List JSON documents (plans, manifests, merge reports) under ``root``."""
    summaries: list[ArtifactSummary] = []
    for current, _dirs, files in os.walk(root):
        for name in files:
            file_path = Path(current) / name
            summary = _summarize(root, file_path)
            if summary is not None and summary.format == "json":
                summaries.append(summary)
    summaries.sort(key=lambda item: item.relative_path)
    return summaries


def summary_to_dict(summary: ArtifactSummary) -> dict:
    return asdict(summary)
