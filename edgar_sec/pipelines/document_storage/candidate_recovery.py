"""Candidate-gated recovery: bundle-first acquisition and processing of pre-2005 filings.

Role-neutral by construction: resolution outcomes are row diagnostics, not abort
signals. No persistence, schema, or worker-loop logic lives here.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from edgar_sec.domain.document.acquisition import (
    AcquiredSubmission,
    BundleFetchResult,
    DocumentReference,
    FetchResult,
    FilingResolutionOutcome,
    SubmissionDocument,
    SubmissionFormat,
    describe_submission_document,
)
from edgar_sec.domain.document.models import (
    DocumentLocator,
    DocumentPathSource,
    FilingOccurrence,
)
from edgar_sec.foundation.serialization import canonical_json
from edgar_sec.pipelines.document_storage.processor import (
    DocumentProcessor,
    ProcessedDocument,
)
from edgar_sec.pipelines.document_storage.resolution import resolve_candidate_filing

log = logging.getLogger("document_storage.candidate_recovery")

#: A delegation target as seen by this module: (document key, document path, exhibit).
DelegationTargetTuple = tuple[str, str, str]


@dataclass(frozen=True, slots=True)
class CandidateOutcome:
    """One emitted row for a candidate locator.

    Fields mirror the 15-column snapshot contract; ``metadata`` is canonical JSON.
    """

    occurrence_id: str
    source_cik: str | None
    accession: str
    document_path: str
    doc_id: str
    form: str
    filing_date: str
    report_date: str | None
    raw_payload: bytes
    norm_text: str
    status: str
    error: str | None
    metadata: str
    parent_locator_key: str | None


def seed_document_reference(locator: DocumentLocator) -> DocumentReference:
    """Role-neutral seed reference for the requested candidate document.

    No body is retained here: the bundle is acquired separately through the fetcher,
    so the seed stays a request rather than a loaded payload.
    """
    from edgar_sec.domain.document.route import content_route

    return DocumentReference(
        locator=locator,
        descriptor=SubmissionDocument(
            document_path=locator.document_path,
            content_route=content_route(locator.document_path),
        ),
        payload=b"",
    )


def _reference_as_acquired(
    ref: DocumentReference,
) -> AcquiredSubmission:
    """Convert a resolution reference to an ``AcquiredSubmission`` for processing."""
    from edgar_sec.domain.document.route import content_route

    return AcquiredSubmission(
        requested_locator=ref.locator,
        source_format=SubmissionFormat.SGML,
        documents=(
            describe_submission_document(
                document_path=ref.descriptor.document_path,
                content_route=content_route(ref.descriptor.document_path),
                sequence=ref.descriptor.sequence,
                doc_type=ref.descriptor.doc_type,
                description=ref.descriptor.description,
            ),
        ),
        selected_index=0,
        selected_payload=ref.payload,
        source=ref.source,
    )


def _outcome_metadata(
    outcome: FilingResolutionOutcome,
    role: str | None,
    parent_locator_key: str | None,
    document_path_source: DocumentPathSource | None,
) -> str:
    out: dict[str, str] = {}
    if role is not None:
        out["document_role"] = role
    if parent_locator_key is not None:
        out["parent_locator_key"] = parent_locator_key
    if document_path_source is not None:
        out["document_path_source"] = str(document_path_source)
    # Outcome on attempted candidates (all bundle resolution outcomes, including
    # unresolved). Non-candidates never reach this code path and stay "{}".
    out["resolution_outcome"] = outcome.value
    return canonical_json(out)


def _emit(
    occurrence_id: str,
    source_cik: str | None,
    accession: str,
    document_path: str,
    doc_id: str,
    form: str,
    filing_date: str,
    report_date: str | None,
    raw_payload: bytes,
    norm_text: str,
    status: str,
    error: str | None,
    metadata: str,
    parent_locator_key: str | None,
) -> CandidateOutcome:
    return CandidateOutcome(
        occurrence_id=occurrence_id,
        source_cik=source_cik,
        accession=accession,
        document_path=document_path,
        doc_id=doc_id,
        form=form,
        filing_date=filing_date,
        report_date=report_date,
        raw_payload=raw_payload,
        norm_text=norm_text,
        status=status,
        error=error,
        metadata=metadata,
        parent_locator_key=parent_locator_key,
    )


def _process_primary_recovered(
    resolution: FilingResolutionResult,
    occurrences: Sequence[FilingOccurrence],
    processor: DocumentProcessor,
) -> tuple[list[CandidateOutcome], list[DelegationTargetTuple]]:
    """Process a recovered primary: requested exhibit plus recovered primary."""
    primary = resolution.primary
    requested = resolution.requested
    primary_path_source = primary.locator.document_path_source
    primary_metadata = _outcome_metadata(
        resolution.outcome,
        role="primary",
        parent_locator_key=None,
        document_path_source=primary_path_source,
    )
    exhibit_metadata = _outcome_metadata(
        resolution.outcome,
        role="exhibit",
        parent_locator_key=primary.locator.document_locator_key,
        document_path_source=requested.locator.document_path_source,
    )

    outcomes: list[CandidateOutcome] = []
    delegations: list[DelegationTargetTuple] = []

    # Requested exhibit: one requested row per original co-filer occurrence.
    for occ in occurrences:
        acquired = _reference_as_acquired(requested)
        try:
            processed = processor.process(acquired)
        except Exception as exc:  # noqa: BLE001 - one body's failure does not discard the other
            outcomes.append(
                _emit(
                    occurrence_id=occ.occurrence_id,
                    source_cik=occ.source_cik.to_10digit(),
                    accession=str(occ.accession),
                    document_path=occ.document_path,
                    doc_id=occ.doc_id,
                    form=occ.form,
                    filing_date=occ.filing_date,
                    report_date=occ.report_date,
                    raw_payload=b"",
                    norm_text="",
                    status="failed",
                    error=str(exc),
                    metadata=exhibit_metadata,
                    parent_locator_key=primary.locator.document_locator_key,
                )
            )
            continue
        outcomes.append(
            _emit(
                occurrence_id=occ.occurrence_id,
                source_cik=occ.source_cik.to_10digit(),
                accession=str(occ.accession),
                document_path=occ.document_path,
                doc_id=occ.doc_id,
                form=occ.form,
                filing_date=occ.filing_date,
                report_date=occ.report_date,
                raw_payload=processed.payload,
                norm_text=processed.text,
                status="ok",
                error=None,
                metadata=exhibit_metadata,
                parent_locator_key=primary.locator.document_locator_key,
            )
        )
        if processed.decision is not None and processed.decision.target_exhibit:
            delegations.append(
                (
                    requested.locator.document_locator_key,
                    requested.locator.document_path,
                    processed.decision.target_exhibit,
                )
            )
        del acquired

    # Recovered primary: one projected row per projected occurrence.
    for projected in resolution.primary_occurrences:
        acquired = _reference_as_acquired(primary)
        try:
            processed = processor.process(acquired)
        except Exception as exc:  # noqa: BLE001 - one body's failure does not discard the other
            outcomes.append(
                _emit(
                    occurrence_id=projected.occurrence_id,
                    source_cik=projected.source_cik.to_10digit(),
                    accession=str(projected.accession),
                    document_path=projected.document_path,
                    doc_id=projected.doc_id,
                    form=projected.form,
                    filing_date=projected.filing_date,
                    report_date=projected.report_date,
                    raw_payload=b"",
                    norm_text="",
                    status="failed",
                    error=str(exc),
                    metadata=primary_metadata,
                    parent_locator_key=None,
                )
            )
            continue
        outcomes.append(
            _emit(
                occurrence_id=projected.occurrence_id,
                source_cik=projected.source_cik.to_10digit(),
                accession=str(projected.accession),
                document_path=projected.document_path,
                doc_id=projected.doc_id,
                form=projected.form,
                filing_date=projected.filing_date,
                report_date=projected.report_date,
                raw_payload=processed.payload,
                norm_text=processed.text,
                status="ok",
                error=None,
                metadata=primary_metadata,
                parent_locator_key=None,
            )
        )
        if processed.decision is not None and processed.decision.target_exhibit:
            delegations.append(
                (
                    primary.locator.document_locator_key,
                    primary.locator.document_path,
                    processed.decision.target_exhibit,
                )
            )
        del acquired

    return outcomes, delegations


def _process_requested_is_primary(
    resolution: FilingResolutionResult,
    occurrences: Sequence[FilingOccurrence],
    processor: DocumentProcessor,
) -> tuple[list[CandidateOutcome], list[DelegationTargetTuple]]:
    """Process a requested document that the resolver confirms is the primary."""
    primary = resolution.primary
    assert primary is resolution.requested
    metadata = _outcome_metadata(
        resolution.outcome,
        role="primary",
        parent_locator_key=None,
        document_path_source=primary.locator.document_path_source,
    )

    outcomes: list[CandidateOutcome] = []
    delegations: list[DelegationTargetTuple] = []

    acquired = _reference_as_acquired(primary)
    try:
        processed = processor.process(acquired)
    except Exception as exc:  # noqa: BLE001
        # The bundle contained the body but processing failed: emit once per
        # occurrence as a failed row, outcome preserved in metadata.
        for occ in occurrences:
            outcomes.append(
                _emit(
                    occurrence_id=occ.occurrence_id,
                    source_cik=occ.source_cik.to_10digit(),
                    accession=str(occ.accession),
                    document_path=occ.document_path,
                    doc_id=occ.doc_id,
                    form=occ.form,
                    filing_date=occ.filing_date,
                    report_date=occ.report_date,
                    raw_payload=b"",
                    norm_text="",
                    status="failed",
                    error=str(exc),
                    metadata=metadata,
                    parent_locator_key=None,
                )
            )
        del acquired
        return outcomes, delegations

    for occ in occurrences:
        outcomes.append(
            _emit(
                occurrence_id=occ.occurrence_id,
                source_cik=occ.source_cik.to_10digit(),
                accession=str(occ.accession),
                document_path=occ.document_path,
                doc_id=occ.doc_id,
                form=occ.form,
                filing_date=occ.filing_date,
                report_date=occ.report_date,
                raw_payload=processed.payload,
                norm_text=processed.text,
                status="ok",
                error=None,
                metadata=metadata,
                parent_locator_key=None,
            )
        )
        if processed.decision is not None and processed.decision.target_exhibit:
            delegations.append(
                (
                    primary.locator.document_locator_key,
                    primary.locator.document_path,
                    processed.decision.target_exhibit,
                )
            )
    del acquired
    return outcomes, delegations


def _emit_fallback(
    fetch_result: FetchResult,
    processed: ProcessedDocument | None,
    outcome: FilingResolutionOutcome,
    occurrences: Sequence[FilingOccurrence],
    document_path_source: DocumentPathSource | None,
) -> list[CandidateOutcome]:
    """Emit the requested row(s) after an ordinary fallback fetch."""
    acquired = fetch_result.acquired
    if acquired is None:
        return [
            _emit(
                occurrence_id=occ.occurrence_id,
                source_cik=occ.source_cik.to_10digit(),
                accession=str(occ.accession),
                document_path=occ.document_path,
                doc_id=occ.doc_id,
                form=occ.form,
                filing_date=occ.filing_date,
                report_date=occ.report_date,
                raw_payload=b"",
                norm_text="",
                status=fetch_result.status,
                error=fetch_result.error or "payload unavailable",
                metadata=_outcome_metadata(
                    outcome,
                    role=None,
                    parent_locator_key=None,
                    document_path_source=document_path_source,
                ),
                parent_locator_key=None,
            )
            for occ in occurrences
        ]

    if processed is None:
        return [
            _emit(
                occurrence_id=occ.occurrence_id,
                source_cik=occ.source_cik.to_10digit(),
                accession=str(occ.accession),
                document_path=occ.document_path,
                doc_id=occ.doc_id,
                form=occ.form,
                filing_date=occ.filing_date,
                report_date=occ.report_date,
                raw_payload=b"",
                norm_text="",
                status="failed",
                error="requested-document processing failed",
                metadata=_outcome_metadata(
                    outcome,
                    role=None,
                    parent_locator_key=None,
                    document_path_source=document_path_source,
                ),
                parent_locator_key=None,
            )
            for occ in occurrences
        ]

    return [
        _emit(
            occurrence_id=occ.occurrence_id,
            source_cik=occ.source_cik.to_10digit(),
            accession=str(occ.accession),
            document_path=occ.document_path,
            doc_id=occ.doc_id,
            form=occ.form,
            filing_date=occ.filing_date,
            report_date=occ.report_date,
            raw_payload=processed.payload,
            norm_text=processed.text,
            status="ok",
            error=None,
            metadata=_outcome_metadata(
                outcome,
                role=None,
                parent_locator_key=None,
                document_path_source=document_path_source,
            ),
            parent_locator_key=None,
        )
        for occ in occurrences
    ]


def run_candidate_recovery(
    locator: DocumentLocator,
    occurrences: Sequence[FilingOccurrence],
    fetcher: ArchiveFetcher,
    processor: DocumentProcessor,
) -> tuple[list[CandidateOutcome], list[DelegationTargetTuple]]:
    """Bundle-first recovery for a ``BUNDLE_CANDIDATE``; one outcome per emitted row.

    Release bundle/envelope results before processing so only one body is resident.
    """
    # 1. Acquire the complete bundle.
    try:
        bundle_result = fetcher.fetch_bundle(locator)
    except Exception as exc:  # noqa: BLE001 - acquisition failures become typed results
        bundle_result = BundleFetchResult(
            status="failed", error=str(exc) or type(exc).__name__
        )

    # 2. Resolve against the bundle (pure, role-neutral).
    seed = seed_document_reference(locator)
    resolution = resolve_candidate_filing(seed, occurrences, bundle_result)

    # 3. Release bundle/envelope results before processing bodies or the fallback
    #    fetch, so only one document body is resident at a time.
    del bundle_result

    if resolution.outcome is FilingResolutionOutcome.PRIMARY_RECOVERED:
        outcomes, delegations = _process_primary_recovered(
            resolution, occurrences, processor
        )
        del resolution
    elif resolution.outcome is FilingResolutionOutcome.REQUESTED_IS_PRIMARY:
        outcomes, delegations = _process_requested_is_primary(
            resolution, occurrences, processor
        )
        del resolution
    else:
        # Unresolved: release the resolution and fall back to the ordinary
        # requested-document fetch to retain the currently supported requested-body
        # behavior.
        resolution_outcome = resolution.outcome
        del resolution
        fetch_result = fetcher.fetch(locator)
        if fetch_result.ok:
            try:
                processed = processor.process(fetch_result.acquired)
            except Exception as exc:  # noqa: BLE001
                processed = None
            outcomes = _emit_fallback(
                fetch_result,
                processed,
                resolution_outcome,
                occurrences,
                locator.document_path_source,
            )
        else:
            outcomes = _emit_fallback(
                fetch_result,
                None,
                resolution_outcome,
                occurrences,
                locator.document_path_source,
            )
        delegations = []

    return outcomes, delegations


def outcome_batch(outcome: CandidateOutcome) -> dict[str, list]:
    """Assemble the 15-column snapshot batch for one candidate outcome."""
    return {
        "occurrence_id": [outcome.occurrence_id],
        "source_cik": [outcome.source_cik],
        "accession": [outcome.accession],
        "document_path": [outcome.document_path],
        "document_locator_key": [outcome.doc_id],
        "blob_hash": [outcome.doc_id],
        "form": [outcome.form],
        "filing_date": [outcome.filing_date],
        "raw_payload": [outcome.raw_payload],
        "byte_size": [len(outcome.raw_payload)],
        "normalized_text": [outcome.norm_text],
        "status": [outcome.status],
        "error_message": [outcome.error],
        "metadata": [outcome.metadata],
        "report_date": [outcome.report_date],
    }


__all__ = ["CandidateOutcome", "run_candidate_recovery"]
