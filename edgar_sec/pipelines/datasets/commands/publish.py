"""Publish command: publish the store index as the next DAG snapshot."""

from __future__ import annotations

from edgar_sec.foundation.runtime.render import KeyValueRow, render_output

from ..options import DatasetsOptions
from ..publish import publish_index


def cmd_publish(options: DatasetsOptions) -> int:
    """Publish the current store index without importing anything."""
    paths = options.datasets_paths()
    outcome = publish_index(paths, branch=options.branch)
    render_output(
        [
            KeyValueRow("command", "publish"),
            KeyValueRow("tip_before", outcome.tip_before or "none"),
            KeyValueRow("published", str(outcome.published)),
            KeyValueRow("snapshot_id", outcome.snapshot_id or "none"),
        ],
        title="Datasets Publish",
    )
    return 0


__all__ = ["cmd_publish"]
