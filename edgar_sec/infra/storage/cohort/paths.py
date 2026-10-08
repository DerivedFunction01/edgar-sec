"""Cohort storage layout and bounded path operations."""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Iterator

import fcntl

from edgar_sec.infra.storage.atomic import atomic_write_json
from edgar_sec.foundation.runtime.paths import ProjectPaths, resolve_paths

COHORTS_DIR_NAME = "cohorts"
CATALOG_DB_NAME = "cohorts.sqlite"
DATASET_FILE_NAME = "ciks.parquet"
FAMILY_INDEX_DIR_NAME = "family_index"
FAMILY_INDEX_FILE_NAME = "company_family.parquet"
STAGING_PREFIX = ".stage-"
STAGING_LEASE_NAME = ".stage.lease"
STAGING_QUARANTINE_PREFIX = f"{STAGING_PREFIX}quarantine-"
STAGING_LEASE_EXPIRY_SECONDS = 120
_SAFE_ID_RE = re.compile(r"^[a-zA-Z0-9_.-]{3,64}$")
_FAMILY_INDEX_ID_RE = re.compile(r"^[a-f0-9]{32}$")
_LOCK_STATE = threading.local()


class PublicationLock:
    def __init__(self, paths: CohortPaths) -> None:
        self.path = paths.cohorts_root / ".publication.lock"
        self._key = str(self.path.resolve())
        self._entered = False
        self._owner_pid: int | None = None

    def __enter__(self) -> PublicationLock:
        locks = getattr(_LOCK_STATE, "locks", None)
        if locks is None:
            locks = {}
            _LOCK_STATE.locks = locks
        state = locks.get(self._key)
        process_id = os.getpid()
        if state is not None and state["pid"] == process_id:
            state["depth"] += 1
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX)
            except BaseException:
                os.close(descriptor)
                raise
            locks[self._key] = {"fd": descriptor, "depth": 1, "pid": process_id}
        self._entered = True
        self._owner_pid = process_id
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if not self._entered or os.getpid() != self._owner_pid:
            return
        locks = _LOCK_STATE.locks
        state = locks[self._key]
        state["depth"] -= 1
        if state["depth"] == 0:
            try:
                fcntl.flock(state["fd"], fcntl.LOCK_UN)
            finally:
                os.close(state["fd"])
                del locks[self._key]
        self._entered = False
        self._owner_pid = None


@dataclass(frozen=True, slots=True)
class CohortPaths:
    artifacts_root: Path

    def __post_init__(self) -> None:
        object.__setattr__(self, "artifacts_root", Path(self.artifacts_root))

    @property
    def cohorts_root(self) -> Path:
        return self.artifacts_root / COHORTS_DIR_NAME

    @property
    def catalog_file(self) -> Path:
        return self.cohorts_root / CATALOG_DB_NAME

    @property
    def family_indices_root(self) -> Path:
        return self.cohorts_root / FAMILY_INDEX_DIR_NAME

    def family_index_dir(self, family_index_id: str) -> Path:
        if not isinstance(family_index_id, str) or not _FAMILY_INDEX_ID_RE.fullmatch(
            family_index_id
        ):
            raise ValueError(f"Invalid family index identifier: {family_index_id!r}")
        cohorts_root = self.cohorts_root.resolve()
        family_root = self.family_indices_root.resolve()
        if family_root.parent != cohorts_root:
            raise ValueError("Family index directory escapes cohorts root")
        target = (family_root / family_index_id).resolve()
        if target.parent != family_root or target.name != family_index_id:
            raise ValueError(
                f"Family index directory escapes root: {family_index_id!r}"
            )
        return target

    def family_index_file(self, family_index_id: str) -> Path:
        return self.family_index_dir(family_index_id) / FAMILY_INDEX_FILE_NAME

    def cohort_dir(self, cohort_id: str) -> Path:
        if (
            not isinstance(cohort_id, str)
            or not _SAFE_ID_RE.fullmatch(cohort_id)
            or ".." in cohort_id
        ):
            raise ValueError(f"Invalid or unsafe cohort identifier: {cohort_id!r}")
        root = self.cohorts_root.resolve()
        path = (self.cohorts_root / cohort_id).resolve()
        if path.parent != root or path.name != cohort_id:
            raise ValueError(f"Cohort directory escapes root: {cohort_id!r}")
        return path

    def cohort_dataset_file(self, cohort_id: str) -> Path:
        return self.cohort_dir(cohort_id) / DATASET_FILE_NAME

    def publication_lock(self) -> PublicationLock:
        return PublicationLock(self)

    def relative_path(self, path: Path | str) -> str:
        root = self.cohorts_root.resolve()
        target = Path(path).resolve()
        try:
            relative = target.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"Path is outside cohorts root: {path!r}") from exc
        if not relative.parts:
            raise ValueError("A cohort artifact path cannot be the storage root")
        return relative.as_posix()

    def resolve_relative_path(self, relative_path: str | Path) -> Path:
        raw = str(relative_path)
        candidate = PurePosixPath(raw)
        if (
            not raw
            or "\\" in raw
            or ":" in raw
            or candidate.is_absolute()
            or candidate.as_posix() != raw
            or any(part in {"", ".", ".."} for part in candidate.parts)
        ):
            raise ValueError(f"Invalid relative cohort path: {raw!r}")
        root = self.cohorts_root.resolve()
        resolved = (root.joinpath(*candidate.parts)).resolve()
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"Cohort path escapes root: {raw!r}") from exc
        return resolved

    def create_staging_dir(self, cohort_id: str) -> Path:
        self.cohort_dir(cohort_id)
        with self.publication_lock():
            self.cohorts_root.mkdir(parents=True, exist_ok=True)
            stage = (
                self.cohorts_root / f"{STAGING_PREFIX}{cohort_id}-{uuid.uuid4().hex}"
            )
            stage.mkdir()
            try:
                self.refresh_staging_lease(stage)
            except BaseException:
                shutil.rmtree(stage, ignore_errors=True)
                raise
            return stage

    def _staging_path(self, staging_dir: Path | str) -> Path:
        stage = Path(staging_dir).resolve()
        if stage.parent != self.cohorts_root.resolve() or not stage.name.startswith(
            STAGING_PREFIX
        ):
            raise ValueError(f"Invalid staging directory: {staging_dir!r}")
        return stage

    def refresh_staging_lease(
        self, staging_dir: Path | str, *, now: datetime | None = None
    ) -> dict[str, object]:
        stage = self._staging_path(staging_dir)
        timestamp = (now or datetime.now(UTC)).astimezone(UTC).isoformat()
        lease_path = stage / STAGING_LEASE_NAME
        try:
            prior = json.loads(lease_path.read_text(encoding="utf-8"))
            created_at = prior["created_at"]
            if not isinstance(created_at, str):
                raise ValueError("invalid stage lease creation time")
            created_timestamp = datetime.fromisoformat(created_at)
            if created_timestamp.tzinfo is None:
                raise ValueError("stage lease timestamps must include a timezone")
        except (OSError, ValueError, KeyError, TypeError):
            created_at = timestamp
        lease = {
            "host": socket.gethostname(),
            "pid": os.getpid(),
            "created_at": created_at,
            "heartbeat": timestamp,
        }
        with self.publication_lock():
            atomic_write_json(lease_path, lease)
        return lease

    def staging_lease_is_unexpired(
        self,
        staging_dir: Path | str,
        *,
        now: datetime | None = None,
        expiry_seconds: int = STAGING_LEASE_EXPIRY_SECONDS,
    ) -> bool | None:
        stage = self._staging_path(staging_dir)
        try:
            lease = json.loads((stage / STAGING_LEASE_NAME).read_text(encoding="utf-8"))
            if (
                not isinstance(lease, dict)
                or not isinstance(lease.get("host"), str)
                or not lease["host"]
                or not isinstance(lease.get("pid"), int)
                or isinstance(lease["pid"], bool)
                or lease["pid"] <= 0
                or not isinstance(lease.get("created_at"), str)
                or not isinstance(lease.get("heartbeat"), str)
            ):
                return None
            created_at = datetime.fromisoformat(lease["created_at"])
            heartbeat = datetime.fromisoformat(lease["heartbeat"])
            if created_at.tzinfo is None or heartbeat.tzinfo is None:
                return None
            current = now or datetime.now(UTC)
            age = (current - heartbeat.astimezone(UTC)).total_seconds()
            return age <= expiry_seconds
        except (OSError, ValueError, TypeError):
            return None

    @contextmanager
    def active_staging_lease(
        self, staging_dir: Path | str, *, heartbeat_interval: float = 30.0
    ) -> Iterator[None]:
        if heartbeat_interval <= 0:
            raise ValueError("heartbeat_interval must be positive")
        stage = self._staging_path(staging_dir)
        self.refresh_staging_lease(stage)
        stopped = threading.Event()
        failures: list[OSError] = []

        def heartbeat() -> None:
            while not stopped.wait(heartbeat_interval):
                try:
                    self.refresh_staging_lease(stage)
                except OSError as error:
                    failures.append(error)
                    return

        worker = threading.Thread(target=heartbeat, daemon=True)
        worker.start()
        try:
            yield
        except BaseException:
            stopped.set()
            worker.join()
            raise
        else:
            stopped.set()
            worker.join()
            if failures:
                raise failures[0]

    def publish_staging_dir(self, cohort_id: str, staging_dir: Path | str) -> Path:
        self.cohort_dir(cohort_id)
        stage = self._staging_path(staging_dir)
        root = self.cohorts_root.resolve()
        if stage.parent != root or not stage.name.startswith(
            f"{STAGING_PREFIX}{cohort_id}-"
        ):
            raise ValueError(f"Invalid staging directory: {staging_dir!r}")
        target = self.cohort_dir(cohort_id)
        with self.publication_lock():
            if target.exists():
                raise FileExistsError(target)
            (stage / STAGING_LEASE_NAME).unlink(missing_ok=True)
            os.replace(stage, target)
        return target

    def list_staging_dirs(self) -> list[Path]:
        if not self.cohorts_root.is_dir():
            return []
        return sorted(
            (
                entry
                for entry in self.cohorts_root.iterdir()
                if entry.is_dir() and entry.name.startswith(STAGING_PREFIX)
            ),
            key=lambda entry: entry.name,
        )

    def remove_staging_dir(self, staging_dir: Path | str) -> None:
        stage = self._staging_path(staging_dir)
        with self.publication_lock():
            if stage.is_dir():
                shutil.rmtree(stage)


def resolve_cohort_paths(
    artifacts_root: Path | str | None = None,
    *,
    project_paths: ProjectPaths | None = None,
) -> CohortPaths:
    if artifacts_root is not None:
        root = Path(artifacts_root)
    elif project_paths is not None:
        root = project_paths.artifacts_root
    else:
        root = resolve_paths().artifacts_root
    return CohortPaths(root)


__all__ = [
    "CATALOG_DB_NAME",
    "COHORTS_DIR_NAME",
    "CohortPaths",
    "DATASET_FILE_NAME",
    "FAMILY_INDEX_DIR_NAME",
    "FAMILY_INDEX_FILE_NAME",
    "PublicationLock",
    "STAGING_LEASE_EXPIRY_SECONDS",
    "STAGING_LEASE_NAME",
    "STAGING_PREFIX",
    "STAGING_QUARANTINE_PREFIX",
    "resolve_cohort_paths",
]
