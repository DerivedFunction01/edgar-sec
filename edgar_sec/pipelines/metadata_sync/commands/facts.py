"""Facts command: ingest the companyfacts bulk archive and publish the store."""

from __future__ import annotations

from pathlib import Path

from edgar_sec.foundation.runtime.render import KeyValueRow, render_output
from edgar_sec.foundation.runtime.settings import resolve_runtime_settings
from edgar_sec.infra.sec_http.client import SecHttpClient
from edgar_sec.infra.storage.bulk_archive import BulkArchiveStore

from ..companyfacts import COMPANYFACTS_BULK_SOURCE_ID, CompanyFactsArchive
from ..facts_publish import publish_facts
from ..facts_store import ingest_facts_archive
from ..paths import resolve_metadata_paths
from .client import build_client


def cmd_facts_ingest(
    *,
    artifacts_root: str | Path | None = None,
    branch: str = "main",
    workers: int | None = None,
    from_store: bool = False,
    http: SecHttpClient | None = None,
) -> int:
    """Download (or reuse) the companyfacts archive, ingest it, and publish."""
    paths = resolve_metadata_paths(artifacts_root)
    store = BulkArchiveStore(paths.bulk_archives_root)
    if from_store:
        reference = store.open(COMPANYFACTS_BULK_SOURCE_ID)
        if reference is None:
            raise ValueError(
                f"no stored archive for source {COMPANYFACTS_BULK_SOURCE_ID!r}"
            )
    else:
        runtime = resolve_runtime_settings()
        client = http or build_client().http
        archive = CompanyFactsArchive.download(
            client,
            store,
            max_bytes=runtime.sec.bulk_archive_max_bytes,
        )
        reference = archive.store_reference
        if reference is None:  # pragma: no cover - download always stores
            raise RuntimeError("companyfacts download produced no stored archive")
    outcome = ingest_facts_archive(paths, reference, workers=workers)
    published = publish_facts(paths, branch=branch)
    render_output(
        [
            KeyValueRow("command", "facts-ingest"),
            KeyValueRow("archive_sha", outcome.archive_sha[:12]),
            KeyValueRow("members", str(outcome.member_count)),
            KeyValueRow("normalized_members", str(outcome.normalized_members)),
            KeyValueRow("carried_members", str(outcome.carried_members)),
            KeyValueRow("removed_members", str(outcome.removed_members)),
            KeyValueRow("fact_rows", str(outcome.fact_rows)),
            KeyValueRow("published", str(published.published)),
            KeyValueRow("snapshot_id", published.snapshot_id or "none"),
        ],
        title="Company Facts Ingest",
    )
    return 0


__all__ = ["cmd_facts_ingest"]
