"""Cohort deletion lifecycle: quarantine, detach, and purge safeguards."""

from __future__ import annotations

import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path

from .errors import (
    CohortActiveSourceError,
    CohortInUseError,
    CohortPinnedError,
)
from .paths import STAGING_PREFIX


class DeletionMixin:
    """Cohort deletion lifecycle mixed into the catalog."""

    def delete_cohort(
        self,
        cohort_id: str,
        purge_dataset: bool = True,
        *,
        force: bool = False,
    ) -> bool:
        with self.paths.publication_lock():
            return self._delete_cohort_locked(cohort_id, purge_dataset, force=force)

    def _delete_cohort_locked(
        self,
        cohort_id: str,
        purge_dataset: bool = True,
        *,
        force: bool = False,
    ) -> bool:
        quarantined: Path | None = None
        marker: Path | None = None
        marker_created = False
        final_dir = self.paths.cohort_dir(cohort_id)
        deleted = False
        try:
            with self._connection() as connection:
                row = connection.execute(
                    "SELECT pinned, dataset_path, dataset_sha256 FROM cohorts "
                    "WHERE cohort_id = ?",
                    (cohort_id,),
                ).fetchone()
                if row is None:
                    return False
                if row["pinned"]:
                    raise CohortPinnedError(f"Cohort {cohort_id!r} is pinned")
                if self._table_exists(connection, "source_active_pointers"):
                    active = connection.execute(
                        "SELECT source_name FROM source_active_pointers WHERE active_snapshot_id = ? LIMIT 1",
                        (cohort_id,),
                    ).fetchone()
                    if active is not None:
                        raise CohortActiveSourceError(
                            f"Cohort {cohort_id!r} is active for source {active['source_name']!r}"
                        )
                aliases_exist = self._table_exists(connection, "object_session_aliases")
                if aliases_exist:
                    alias = connection.execute(
                        "SELECT session_id, alias_name FROM object_session_aliases WHERE target_id = ? LIMIT 1",
                        (cohort_id,),
                    ).fetchone()
                    if alias is not None and not force:
                        raise CohortInUseError(
                            f"Cohort {cohort_id!r} is referenced by a workspace alias"
                        )
                if purge_dataset and final_dir.exists():
                    resolved_root = self.paths.cohorts_root.resolve()
                    target = final_dir.resolve()
                    if target.parent != resolved_root:
                        raise ValueError("cohort purge target escapes cohorts root")
                    quarantined = (
                        resolved_root
                        / f"{STAGING_PREFIX}purge-{cohort_id}-{uuid.uuid4().hex}"
                    )
                    final_dir.rename(quarantined)
                if not purge_dataset:
                    if final_dir.is_symlink() or not final_dir.is_dir():
                        raise FileNotFoundError(final_dir)
                    dataset_file = self.paths.cohort_dataset_file(cohort_id)
                    dataset_recorded = self.paths.resolve_relative_path(
                        row["dataset_path"]
                    )
                    if (
                        dataset_recorded != dataset_file
                        or dataset_file.is_symlink()
                        or not dataset_file.is_file()
                    ):
                        raise FileNotFoundError(dataset_file)
                    marker = final_dir / ".detached"
                    if marker.is_symlink():
                        raise ValueError("detached marker cannot be a symlink")
                    if not marker.exists():
                        marker.touch()
                        marker_created = True
                    connection.execute(
                        "INSERT OR REPLACE INTO detached_cohort_datasets "
                        "(cohort_id, dataset_path, dataset_sha256, detached_at) "
                        "VALUES (?, ?, ?, ?)",
                        (
                            cohort_id,
                            row["dataset_path"],
                            row["dataset_sha256"],
                            datetime.now(UTC).isoformat(),
                        ),
                    )
                if aliases_exist and force:
                    connection.execute(
                        "DELETE FROM object_session_aliases WHERE target_id = ?",
                        (cohort_id,),
                    )
                connection.execute(
                    "DELETE FROM cohorts WHERE cohort_id = ?", (cohort_id,)
                )
            deleted = True
        except BaseException:
            if marker_created and marker is not None:
                marker.unlink(missing_ok=True)
            if (
                quarantined is not None
                and quarantined.exists()
                and not final_dir.exists()
            ):
                quarantined.rename(final_dir)
            raise
        if quarantined is not None:
            shutil.rmtree(quarantined)
        return deleted
