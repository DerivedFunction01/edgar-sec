"""DAG snapshot management console and offline filing retrieval engine."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from edgar_sec.apps.client.models import FilingsResult
from edgar_sec.domain.document.aggregate import FilingAggregate, FilingAttachment
from edgar_sec.apps.runner.config import DateFilterInput
from edgar_sec.domain.filing_catalog.filters import (
    date_selection_matches,
    resolve_date_selection,
)
from edgar_sec.domain.identity import AccessionNumber, Cik
from edgar_sec.engine.forms.render import render_filing
from edgar_sec.foundation.runtime.paths import resolve_paths
from edgar_sec.infra.storage.dag.catalog import DAGCatalog
from edgar_sec.infra.storage.dag.resolution import compile_virtual_views
from edgar_sec.infra.storage.dag.traversal import walk_lineage
from edgar_sec.infra.storage.duckdb import connect, sql_identifier
from edgar_sec.pipelines.document_acquisition.paths import resolve_acquisition_paths
from edgar_sec.pipelines.document_acquisition.snapshot.specs import (
    ACQUISITION_RELATIONS,
)


class SnapshotConsole:
    """Management console for DAG snapshot tags, branches, and retention."""

    def __init__(self, artifacts_root: Path | str | None = None) -> None:
        self.artifacts_root = (
            Path(artifacts_root)
            if artifacts_root is not None
            else resolve_paths().artifacts_root
        )
        self.snapshots_root = resolve_acquisition_paths(
            artifacts_root=self.artifacts_root
        ).snapshots_root

    def _catalog(self) -> DAGCatalog:
        return DAGCatalog(self.snapshots_root)

    def tag(self, name: str, snapshot_id: str | None = None, message: str = "") -> None:
        """Create or update an immutable tag pointing to a snapshot."""
        catalog = self._catalog()
        target_id = snapshot_id
        if target_id is None:
            ptr = catalog.read_pointer("main")
            if ptr is None:
                raise ValueError(
                    "cannot tag without snapshot_id: main branch has no tip"
                )
            target_id = str(ptr["snapshot_id"])
        catalog.create_tag(name, target_id, message=message)

    def tags(self) -> list[dict[str, Any]]:
        """List all registered tags."""
        return self._catalog().list_tags()

    def get_tag(self, name: str) -> dict[str, Any] | None:
        """Retrieve tag record by name."""
        return self._catalog().get_tag(name)

    def delete_tag(self, name: str) -> bool:
        """Delete a tag by name."""
        return self._catalog().delete_tag(name)

    def branches(self) -> dict[str, str]:
        """Return all branch names and their tip snapshot IDs."""
        return self._catalog().list_branches()

    def current(self, branch: str = "main") -> str | None:
        """Return the tip snapshot ID for the given branch."""
        ptr = self._catalog().read_pointer(branch)
        return str(ptr["snapshot_id"]) if ptr is not None else None

    def list(self) -> list[dict[str, Any]]:
        """List all snapshots in topological order."""
        return self._catalog().list_snapshots()

    def gc(self, *, dry_run: bool = False) -> dict[str, Any]:
        """Collect unreferenced snapshots and reclaim disk space."""
        from edgar_sec.infra.storage.dag.retention import (
            analyze_retention,
            purge_unreferenced,
        )

        report = analyze_retention(self.snapshots_root)
        purged = purge_unreferenced(self.snapshots_root, report, dry_run=dry_run)
        return {
            "reclaimed_bytes": report.prunable_byte_size,
            "purged_snapshots": purged,
            "prunable_snapshots": list(report.prunable_snapshots),
            "dry_run": dry_run,
        }


def query_filings_from_snapshot(
    artifacts_root: Path | str | None = None,
    *,
    snapshot_id_or_tag: str = "main",
    forms: Sequence[str] = (),
    ciks: Sequence[str | int] = (),
    dates: DateFilterInput = None,
    limit: int | None = None,
) -> FilingsResult:
    """Hydrate a FilingsResult directly from a published DAG snapshot."""
    root = (
        Path(artifacts_root)
        if artifacts_root is not None
        else resolve_paths().artifacts_root
    )
    snapshots_root = resolve_acquisition_paths(artifacts_root=root).snapshots_root
    catalog = DAGCatalog(snapshots_root)

    resolved_id: str | None = None
    tag = catalog.get_tag(snapshot_id_or_tag)
    if tag is not None:
        resolved_id = str(tag["snapshot_id"])
    else:
        ptr = catalog.read_pointer(snapshot_id_or_tag)
        if ptr is not None:
            resolved_id = str(ptr["snapshot_id"])
        elif catalog.has_snapshot(snapshot_id_or_tag):
            resolved_id = snapshot_id_or_tag

    if resolved_id is None:
        raise ValueError(f"snapshot, tag, or branch not found: {snapshot_id_or_tag!r}")

    lineage = walk_lineage(snapshots_root, resolved_id)

    con = connect()
    try:
        views = compile_virtual_views(
            con, ACQUISITION_RELATIONS, lineage, snapshots_root
        )
        target_results_view = sql_identifier(views["target_results"])
        accession_ciks_view = sql_identifier(views["accession_ciks"])
        source_assets_view = sql_identifier(views["source_assets"])
        acquisition_slots_view = sql_identifier(views["acquisition_slots"])
        slot_types_view = sql_identifier(views["slot_types"])
        text_payloads_view = sql_identifier(views["text_payloads"])
        binary_payloads_view = sql_identifier(views["binary_payloads"])

        target_stmt = (
            f"SELECT DISTINCT "
            f"t.target_id, t.accession, t.form, t.filing_date, t.target_url, "
            f"t.outcome, t.selected_sha256, t.byte_size, "
            f"COALESCE(c.cik, regexp_extract(t.target_url, 'data/([0-9]+)/', 1)) AS cik "
            f"FROM {target_results_view} t "
            f"LEFT JOIN {accession_ciks_view} c ON t.accession = c.accession "
            f"ORDER BY t.accession"
        )
        target_rows = con.execute(target_stmt).fetchall()

        payload_stmt = (
            f"SELECT payload_sha256, payload_bytes FROM {text_payloads_view} "
            f"UNION ALL "
            f"SELECT payload_sha256, payload_bytes FROM {binary_payloads_view}"
        )
        payload_map: dict[str, bytes] = {}
        for p_sha, p_bytes in con.execute(payload_stmt).fetchall():
            if p_sha and p_bytes is not None:
                payload_map[str(p_sha)] = bytes(p_bytes)

        att_stmt = (
            f"SELECT "
            f"s.accession, s.sequence, COALESCE(st.statutory_type, '') AS document_type, "
            f"COALESCE(sa.canonical_path, s.locator) AS filename, "
            f"s.locator AS url "
            f"FROM {acquisition_slots_view} s "
            f"LEFT JOIN {source_assets_view} sa ON s.source_asset_id = sa.source_asset_id "
            f"LEFT JOIN {slot_types_view} st ON s.accession = st.accession AND s.sequence = st.sequence "
            f"ORDER BY s.accession, s.sequence"
        )
        attachments_by_acc: dict[str, list[FilingAttachment]] = {}
        for acc_str, seq, doc_type, fname, loc_url in con.execute(att_stmt).fetchall():
            acc_val = str(acc_str)
            filename = Path(str(fname or "")).name
            attachments_by_acc.setdefault(acc_val, []).append(
                FilingAttachment(
                    attachment_id=str(seq),
                    document_type=str(doc_type or ""),
                    filename=filename,
                    url=str(loc_url or ""),
                )
            )
    finally:
        con.close()

    target_forms = {f.upper() for f in forms} if forms else None
    target_ciks = {str(Cik.from_raw(c).value).zfill(10) for c in ciks} if ciks else None
    resolved_dates = resolve_date_selection(dates)

    filings: list[FilingAggregate] = []
    for row in target_rows:
        tid, acc_str, form, fdate, turl, outcome, sha, bsize, raw_cik = row
        f_norm = str(form).upper()
        if target_forms is not None and f_norm not in target_forms:
            continue
        cik_clean = str(Cik.from_raw(raw_cik).value).zfill(10) if raw_cik else None
        if target_ciks is not None and cik_clean not in target_ciks:
            continue
        date_val = str(fdate or "")
        if resolved_dates and not date_selection_matches(date_val, resolved_dates):
            continue

        acc = AccessionNumber.from_any(acc_str)
        cik_inst = Cik.from_raw(raw_cik) if raw_cik else Cik.from_raw(1)
        body = payload_map.get(str(sha)) if sha else None
        atts = tuple(attachments_by_acc.get(str(acc_str), ()))

        filing = FilingAggregate(
            accession=acc,
            primary_cik=cik_inst,
            ciks=(cik_inst,),
            form=str(form),
            filing_date=date_val,
            primary_document_path=str(turl).split("/")[-1] if turl else "",
            primary_sha256=str(sha) if sha else None,
            primary_storage_path=None,
            primary_document_url=str(turl or ""),
            attachments=atts,
            fetcher=(lambda data=body: lambda f: data)(),
            renderer=lambda f, operation=None: render_filing(
                f, operation=operation or "raw"
            ),
        )
        filings.append(filing)
        if limit is not None and len(filings) >= int(limit):
            break

    return FilingsResult(
        run_id=f"snapshot-{resolved_id}",
        plan_id="",
        target_parquet_glob="",
        run_state_sqlite_path=Path(""),
        artifacts_root=root,
        snapshot_id=resolved_id,
        items=tuple(filings),
    )


__all__ = [
    "SnapshotConsole",
    "query_filings_from_snapshot",
]
