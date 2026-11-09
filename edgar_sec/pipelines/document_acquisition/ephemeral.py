"""Enumerate and acquire non-primary run intents from filing index pages."""

from __future__ import annotations

from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from edgar_sec.domain.document_inventory.models import (
    IndexPageInput,
    ParsedIndexPage,
)
from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.domain.sec_urls import index_url_for
from edgar_sec.engine.index_pages.enumeration import (
    EnumeratedTarget,
    TargetIntent,
    enumerate_index_targets,
)
from edgar_sec.engine.index_pages.parser import parse_html_index
from edgar_sec.foundation.serialization import canonical_hash
from edgar_sec.infra.sec_http.streaming import StreamFailure
from edgar_sec.pipelines.document_acquisition.attempts import relative_path
from edgar_sec.pipelines.document_acquisition.models import AcquisitionPolicy
from edgar_sec.pipelines.document_acquisition.paths import AcquisitionPaths
from edgar_sec.pipelines.document_acquisition.runner_support import (
    AcquisitionTransport,
    new_staging_path,
    stream,
)
from edgar_sec.pipelines.document_acquisition.run_state.ephemeral import (
    record_ephemeral_targets,
)


def run_ephemeral_pass(
    *,
    run_id: str,
    accessions: tuple[str, ...],
    intents: tuple[TargetIntent, ...],
    paths: AcquisitionPaths,
    policy: AcquisitionPolicy,
    transport: AcquisitionTransport,
    workers: int,
) -> dict[str, int]:
    """Fetch each accession's index page in the pool and acquire its matches.

    Resolutions are recorded in the run's own state store and nowhere else:
    no plan, manifest, or inventory record is created for them.
    """
    staging_root = paths.run_staging_root(run_id)
    staging_root.mkdir(parents=True, exist_ok=True)
    run_root = paths.run_dir(run_id)

    def task(accession: str) -> list[dict[str, Any]]:
        return _accession_rows(
            run_id, accession, intents, staging_root, run_root, policy, transport
        )

    rows: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for accession_rows in pool.map(task, accessions):
            rows.extend(accession_rows)
    record_ephemeral_targets(paths.run_state_path(run_id), rows)
    return dict(sorted(Counter(row["outcome"] for row in rows).items()))


def _accession_rows(
    run_id: str,
    accession_value: str,
    intents: tuple[TargetIntent, ...],
    staging_root: Path,
    run_root: Path,
    policy: AcquisitionPolicy,
    transport: AcquisitionTransport,
) -> list[dict[str, Any]]:
    accession = AccessionNumber.from_any(accession_value)
    url = index_url_for(accession, accession.normalized[:10])
    page_path = new_staging_path(staging_root, "index")
    try:
        result = stream(transport, url, page_path, accession, policy)
        if isinstance(result, StreamFailure):
            return [
                _failure_row(run_id, accession_value, intent, "index_fetch_failed")
                for intent in intents
            ]
        body = page_path.read_bytes()
    finally:
        page_path.unlink(missing_ok=True)
    outcome = parse_html_index(IndexPageInput(accession, url, body))
    if not isinstance(outcome, ParsedIndexPage):
        return [
            _failure_row(run_id, accession_value, intent, "index_not_recognized")
            for intent in intents
        ]
    return [
        _resolution_row(
            run_id,
            accession_value,
            resolution,
            staging_root,
            run_root,
            accession,
            policy,
            transport,
        )
        for resolution in enumerate_index_targets(outcome, intents)
    ]


def _failure_row(
    run_id: str, accession_value: str, intent: TargetIntent, reason: str
) -> dict[str, Any]:
    return {
        "target_id": canonical_hash(
            [run_id, accession_value, intent.request_id, None, "unresolved"]
        ),
        "accession": accession_value,
        "request_id": intent.request_id,
        "target_role": intent.role,
        "target_type": intent.type,
        "document_type": None,
        "entry_id": None,
        "filename": None,
        "target_url": None,
        "sequence": None,
        "byte_size": None,
        "status": "unresolved",
        "status_reason": reason,
        "outcome": "not_acquired",
        "body_relative_path": None,
        "sha256": None,
    }


def _resolution_row(
    run_id: str,
    accession_value: str,
    resolution: EnumeratedTarget,
    staging_root: Path,
    run_root: Path,
    accession: AccessionNumber,
    policy: AcquisitionPolicy,
    transport: AcquisitionTransport,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "target_id": canonical_hash(
            [
                run_id,
                accession_value,
                resolution.request_id,
                resolution.entry_id,
                resolution.status,
            ]
        ),
        "accession": accession_value,
        "request_id": resolution.request_id,
        "target_role": resolution.role,
        "target_type": resolution.type,
        "document_type": resolution.document_type,
        "entry_id": resolution.entry_id,
        "filename": resolution.filename,
        "target_url": resolution.target_url,
        "sequence": resolution.sequence,
        "byte_size": resolution.byte_size,
        "status": resolution.status,
        "status_reason": resolution.status_reason,
        "outcome": "not_acquired",
        "body_relative_path": None,
        "sha256": None,
    }
    if resolution.status != "matched" or resolution.target_url is None:
        return row
    destination = new_staging_path(staging_root, "response")
    result = stream(transport, resolution.target_url, destination, accession, policy)
    if isinstance(result, StreamFailure):
        destination.unlink(missing_ok=True)
        row["outcome"] = "failed"
        row["status_reason"] = "document_fetch_failed"
        return row
    row["outcome"] = "acquired"
    row["body_relative_path"] = relative_path(run_root, destination)
    row["sha256"] = result.sha256
    row["byte_size"] = result.byte_size
    return row


__all__ = ["run_ephemeral_pass"]
