"""Stored-data surface of the Edgar facade: bulk archives and published snapshots."""

from __future__ import annotations

from typing import TYPE_CHECKING, Sequence

from edgar_sec.apps.runner.config import DateFilterInput

if TYPE_CHECKING:
    from edgar_sec.apps.client.models import FilingsResult
    from edgar_sec.apps.client.snapshots import SnapshotConsole
    from edgar_sec.infra.storage.bulk_archive import (
        ArchiveReference,
        BulkArchiveStore,
    )


class StoredAccessMixin:
    """Stored-data access methods composed into the Edgar facade."""

    def _bulk_archive_store(self) -> "BulkArchiveStore":
        from edgar_sec.infra.storage.bulk_archive import BulkArchiveStore
        from edgar_sec.pipelines.metadata_sync.paths import resolve_metadata_paths

        metadata = resolve_metadata_paths(self.artifacts_root)
        return BulkArchiveStore(metadata.bulk_archives_root)

    def bulk_archive(
        self, source_id: str, sha256: str | None = None
    ) -> "ArchiveReference | None":
        """Reference to a stored bulk archive, or ``None`` when unstored.

        Read-only: the facade never downloads; absence is reported, not
        repaired. The reference carries identity, manifest, and stored paths.
        """
        return self._bulk_archive_store().open(source_id, sha256)

    def bulk_archive_member(
        self, source_id: str, member_name: str, sha256: str | None = None
    ) -> bytes | None:
        """One member's bytes from a stored bulk archive.

        ``None`` when the source is unstored; an unknown member of a stored
        archive raises, as the store does.
        """
        store = self._bulk_archive_store()
        reference = store.open(source_id, sha256)
        if reference is None:
            return None
        return store.read_member(reference, member_name)

    def from_snapshot(
        self,
        snapshot_or_tag: str = "main",
        *,
        forms: Sequence[str] | str = (),
        ciks: Sequence[str | int] | str | int = (),
        dates: DateFilterInput = None,
        limit: int | None = None,
    ) -> FilingsResult:
        """Hydrate filings directly and offline from a published DAG snapshot."""
        from edgar_sec.apps.client.snapshots import query_filings_from_snapshot

        form_tuple = (
            (forms,) if isinstance(forms, str) else tuple(str(f) for f in forms)
        )
        cik_tuple = (
            (str(ciks),)
            if isinstance(ciks, (str, int))
            else tuple(str(c) for c in ciks)
        )
        return query_filings_from_snapshot(
            self.artifacts_root,
            snapshot_id_or_tag=snapshot_or_tag,
            forms=form_tuple,
            ciks=cik_tuple,
            dates=dates,
            limit=limit,
        )

    @property
    def snapshots(self) -> SnapshotConsole:
        """Return SnapshotConsole instance bound to this facade."""
        from edgar_sec.apps.client.snapshots import SnapshotConsole

        return SnapshotConsole(self.artifacts_root)
