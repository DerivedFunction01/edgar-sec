"""Source synchronization and comparison commands."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from edgar_sec.foundation.runtime.render import KeyValueRow, render_output
from edgar_sec.pipelines.metadata_sync.family_index import ensure_family_index
from edgar_sec.pipelines.metadata_sync.options import PlanOptions
from edgar_sec.pipelines.metadata_sync.paths import resolve_metadata_paths
from edgar_sec.pipelines.metadata_sync.registry import compare_sources
from edgar_sec.pipelines.metadata_sync.source_registry import (
    SOURCE_NAME,
    SOURCE_UNIVERSE_NAME,
    refresh_cik_lookup_universe,
    refresh_company_tickers,
)


def cmd_refresh(
    artifacts_root: Path | None = None, *, source: str = SOURCE_NAME
) -> int:
    """Fetch and publish one immutable external source snapshot."""
    metadata = resolve_metadata_paths(artifacts_root)
    if source == SOURCE_UNIVERSE_NAME:
        manifest = refresh_cik_lookup_universe(metadata_paths=metadata)
        count = manifest.get("line_count", manifest.get("row_count", 0))
    else:
        manifest = refresh_company_tickers(metadata_paths=metadata)
        count = manifest.get("row_count", 0)
    render_output(
        [
            KeyValueRow("source", source),
            KeyValueRow("snapshot_id", manifest["snapshot_id"]),
            KeyValueRow("row_count", str(count)),
        ],
        title=f"Source Refreshed ({source})",
    )
    return 0


def cmd_family_index(artifacts_root: Path | None = None) -> int:
    """Assign a company family to every registrant of the published universe."""
    metadata = resolve_metadata_paths(artifacts_root)
    artifact = ensure_family_index(metadata)
    summary = _family_index_summary(artifact.manifest_path)
    render_output(
        [
            KeyValueRow("family_index_id", artifact.family_index_id),
            KeyValueRow("registrants", str(summary.get("registrants", 0))),
            KeyValueRow("entity_families", str(summary.get("entity_families", 0))),
            KeyValueRow("spv_families", str(summary.get("spv_families", 0))),
            KeyValueRow("singletons", str(summary.get("singletons", 0))),
        ],
        title="Family Index Published",
    )
    return 0


def _family_index_summary(manifest_path: Path) -> dict[str, Any]:
    """Return summary counts recorded in a family index manifest."""
    recorded = json.loads(manifest_path.read_text(encoding="utf-8"))
    return {
        key: recorded[key]
        for key in (
            "schema_version",
            "roster_id",
            "dataset_sha256",
            "assignment_sha256",
            "rules_fingerprint",
            "registrants",
            "entity_families",
            "spv_families",
            "singletons",
            "spv_registrants",
            "unresolved_sponsors",
        )
    }


def cmd_compare(options: PlanOptions, *, source_manifest: Path) -> int:
    """Project the curated CIK input against a published source snapshot."""
    if options.input_path is None:
        raise ValueError("sources compare needs --input")
    summary = compare_sources(
        curated_input_path=options.input_path,
        source_manifest_path=source_manifest,
        metadata_paths=resolve_metadata_paths(options.artifacts_root),
    )
    render_output(
        [
            KeyValueRow("registry_id", summary.get("registry_id", "")),
            KeyValueRow("source", summary.get("source", "")),
            KeyValueRow("new_cik_count", str(summary.get("new_cik_count", 0))),
            KeyValueRow("roster_id", summary.get("roster_id", "")),
        ],
        title="Sources Compared",
    )
    return 0
