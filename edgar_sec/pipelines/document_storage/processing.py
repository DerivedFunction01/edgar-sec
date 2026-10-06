"""Row assembly and the ordinary fetch/process/delegate path for one locator.

These helpers serve the worker loop's ordinary (non-candidate) path; the candidate
path delegates to candidate_recovery instead.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from pathlib import Path

from edgar_sec.domain.document.models import (
    DocumentLocator,
    FilingOccurrence,
    derive_document_locator_key,
)
from edgar_sec.infra.storage.atomic import atomic_write_json
from edgar_sec.infra.storage.parquet import StagedParquetWriter
from edgar_sec.pipelines.document_storage.checkpoint import DOCUMENT_SNAPSHOT_SCHEMA
from edgar_sec.pipelines.document_storage.fetching import ArchiveFetcher
from edgar_sec.pipelines.document_storage.processor import (
    DocumentProcessor,
    ProcessedDocument,
)
from edgar_sec.pipelines.document_storage.work_order import DelegationTarget, FilingWork

log = logging.getLogger("document_storage.processing")


def _build_snapshot_batch(
    occurrences: Sequence[FilingOccurrence],
    *,
    raw_payload: bytes,
    norm_text: str,
    status: str,
    error: str | None,
    metadata_map: Mapping[str, str] | None = None,
    report_dates: Mapping[str, str | None] | None = None,
) -> dict[str, list]:
    """Assemble a columnar batch dictionary conforming to DOCUMENT_SNAPSHOT_SCHEMA."""
    metadata_map = metadata_map or {}
    report_dates = report_dates or {}

    report_date_list = []
    metadata_list = []
    for occ in occurrences:
        report_date_list.append(report_dates.get(occ.occurrence_id, occ.report_date))
        metadata_list.append(metadata_map.get(occ.occurrence_id, "{}"))

    return {
        "occurrence_id": [occ.occurrence_id for occ in occurrences],
        "source_cik": [occ.source_cik.to_10digit() for occ in occurrences],
        "accession": [str(occ.accession) for occ in occurrences],
        "document_path": [occ.document_path for occ in occurrences],
        "document_locator_key": [
            derive_document_locator_key(str(occ.accession), occ.document_path)
            for occ in occurrences
        ],
        "blob_hash": [occ.doc_id for occ in occurrences],
        "form": [occ.form for occ in occurrences],
        "filing_date": [occ.filing_date for occ in occurrences],
        "raw_payload": [raw_payload] * len(occurrences),
        "byte_size": [len(raw_payload)] * len(occurrences),
        "normalized_text": [norm_text] * len(occurrences),
        "status": [status] * len(occurrences),
        "error_message": [error] * len(occurrences),
        "metadata": metadata_list,
        "report_date": report_date_list,
    }


def _process_locator(
    locator: DocumentLocator,
    work: FilingWork,
    fetcher: ArchiveFetcher,
    processor: DocumentProcessor,
    payload_sink: Callable[[DocumentLocator, bytes], None] | None,
    delegations: list[DelegationTarget],
    delegations_file: Path,
    writer: StagedParquetWriter,
) -> None:
    """Fetch and process one locator via the ordinary path.

    Writes its batch to ``writer`` and records any stub delegation target.
    """
    result = fetcher.fetch(locator)
    work = replace(
        work,
        status=result.status,
        error=result.error,
        acquired=result.acquired,
    )
    acquired = work.acquired
    if acquired is None:
        writer.write_batch(
            _build_snapshot_batch(
                work.occurrences,
                raw_payload=b"",
                norm_text="",
                status="missing",
                error=work.error or "payload unavailable",
                metadata_map={},
                report_dates=_occurrence_report_dates(work.occurrences),
            )
        )
        return

    # The result also holds the source envelope, which spans the whole submission.
    # Releasing it here keeps one envelope out of memory for the normalize call.
    del result
    if payload_sink is not None:
        payload_sink(locator, acquired.selected_payload)

    try:
        processed: ProcessedDocument = processor.process(acquired)
    except Exception as exc:  # noqa: BLE001 - one bad document is not a bad chunk
        log.warning("processing failed for %s: %s", locator.document_path, exc)
        work = replace(work, status="failed", error=str(exc))
        writer.write_batch(
            _build_snapshot_batch(
                work.occurrences,
                raw_payload=b"",
                norm_text="",
                status="failed",
                error=work.error,
                metadata_map={},
                report_dates=_occurrence_report_dates(work.occurrences),
            )
        )
        return

    work = replace(work, processed=processed, status="ok")
    if processed.decision is not None and processed.decision.target_exhibit:
        _record_delegation(
            delegations,
            delegations_file,
            locator.document_locator_key,
            locator.document_path,
            processed.decision.target_exhibit,
        )

    writer.write_batch(
        _build_snapshot_batch(
            work.occurrences,
            raw_payload=processed.payload,
            norm_text=processed.text,
            status=work.status,
            error=None,
            metadata_map={},
            report_dates=_occurrence_report_dates(work.occurrences),
        )
    )


def _record_delegation(
    delegations: list[DelegationTarget],
    delegations_file: Path,
    document_locator_key: str,
    document_path: str,
    target_exhibit: str,
) -> None:
    """Append one delegation target and persist it atomically."""
    delegations.append(
        DelegationTarget(
            document_locator_key=document_locator_key,
            document_path=document_path,
            target_exhibit=target_exhibit,
        )
    )
    try:
        atomic_write_json(
            delegations_file,
            [
                {
                    "document_locator_key": d.document_locator_key,
                    "document_path": d.document_path,
                    "target_exhibit": d.target_exhibit,
                }
                for d in delegations
            ],
            canonical=True,
        )
    except OSError:
        pass


def _occurrence_report_dates(
    occurrences: Sequence[FilingOccurrence],
) -> dict[str, str | None]:
    return {occ.occurrence_id: occ.report_date for occ in occurrences}


__all__ = [
    "_build_snapshot_batch",
    "_occurrence_report_dates",
    "_process_locator",
    "_record_delegation",
]
