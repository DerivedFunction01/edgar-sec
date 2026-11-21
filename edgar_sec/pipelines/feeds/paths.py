"""Directory layout for the feeds ledger pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import edgar_sec.foundation.runtime.paths as foundation_paths
from edgar_sec.foundation.runtime.paths import (
    ProjectPaths,
    resolve_paths,
    transient_dir,
    validate_safe_id,
)
from edgar_sec.infra.storage.dag.paths import DAGPaths

FEEDS_DIR = "feeds"
FEED_EVENTS_FILE = "feed_events.parquet"


@dataclass(frozen=True, slots=True)
class FeedsPaths:
    """Root-scoped feeds ledger layout, independent of any single run."""

    artifacts_root: Path

    @property
    def feeds_root(self) -> Path:
        """Root of the published feeds ledger dataset."""
        return self.artifacts_root / FEEDS_DIR

    @property
    def snapshots_root(self) -> Path:
        """Root of published ledger snapshot directories, and of the pointer."""
        return self.feeds_root / foundation_paths.SNAPSHOTS_DIR

    @property
    def catalog_file(self) -> Path:
        """SQLite DAG catalog database for published ledger snapshots."""
        return DAGPaths(self.snapshots_root).catalog_file

    def snapshot_dir(self, snapshot_id: str) -> Path:
        """Directory holding one immutable ledger snapshot."""
        return self.snapshots_root / validate_safe_id(snapshot_id)

    def snapshot_events_file(self, snapshot_id: str) -> Path:
        """The feed-events part published inside one snapshot."""
        return self.snapshot_dir(snapshot_id) / FEED_EVENTS_FILE

    def transient_dir(self, run_id: str) -> Path:
        """Staging directory for one ledger run, never published."""
        return transient_dir(self.artifacts_root, FEEDS_DIR, validate_safe_id(run_id))


def resolve_feeds_paths(
    artifacts_root: str | Path | None = None,
    project_paths: ProjectPaths | None = None,
) -> FeedsPaths:
    """Resolve the feeds layout from an explicit root or the project default."""
    if artifacts_root is not None:
        return FeedsPaths(artifacts_root=Path(artifacts_root).resolve())
    if project_paths is not None:
        return FeedsPaths(artifacts_root=project_paths.artifacts_root)
    return FeedsPaths(artifacts_root=resolve_paths().artifacts_root)


__all__ = [
    "FEEDS_DIR",
    "FEED_EVENTS_FILE",
    "FeedsPaths",
    "resolve_feeds_paths",
]
