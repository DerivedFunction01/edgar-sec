"""Exhibit second pass and filing-year annotation helpers.

The worker's exhibit second pass (Checkpoint C of the extraction decision
tree): after a form evaluator emits ``REFETCH_SUB_DOC``, the targeted exhibit
is resolved — preferring the PEM-stripped bundle bytes retained from
acquisition — normalized, and persisted as its own blob + normalized row.
Failures land in ``normalization_failures`` with an ``exhibit_refetch:``
prefix; they are never silently dropped.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any

from defs.filing_identity import accession_hyphenated, normalize_accession
from defs.sec_documents.sgml import has_sgml_documents
from defs.sql import (
    Compare,
    ComparisonOp,
    DoNothing,
    Update,
    col,
    insert_values,
    param,
)

from ..processors import DocumentProcessor, execute_processor
from .fetcher import locate_sub_document_with_filename
from .schemas import (
    DOCUMENT_BLOBS_TABLE,
    NORMALIZATION_FAILURES_TABLE,
    NORMALIZED_DOCUMENTS_TABLE,
    NORMALIZED_SCHEMA_VERSION,
    DocumentLocator,
    FilingOccurrence,
    NormalizationFailure,
    NormalizedDocument,
    build_blob,
    compress_payload,
    deterministic_metadata,
    doc_id,
    normalized_artifact_id,
)

EXHIBIT_REFETCH_ERROR_PREFIX = "exhibit_refetch: "


class _LocatorWithYear:
    """Locator view annotated with ``filing_year`` for evaluator fast paths.

    The form evaluators key their post-2011 bypass on
    ``preprocessed.metadata["filing_year"]``; the processor copies it from the
    locator when present. ``DocumentLocator`` is frozen with slots, so the
    worker wraps it instead of mutating it. All attributes the processor reads
    (``accession``, ``document_path``, ``form``) delegate to the real locator.
    """

    __slots__ = ("_locator", "filing_year")

    def __init__(self, locator: DocumentLocator, filing_year: int | None) -> None:
        self._locator = locator
        self.filing_year = filing_year

    def __getattr__(self, name: str) -> object:
        return getattr(self._locator, name)


def _filing_year_for(
    matching_occs: Sequence[FilingOccurrence],
) -> int | None:
    """Derive the filing year from the first occurrence's filing date."""
    for occ in matching_occs:
        if occ.filing_date:
            try:
                return int(str(occ.filing_date)[:4])
            except ValueError:
                return None
    return None


def with_filing_year(
    locator: DocumentLocator,
    matching_occs: Sequence[FilingOccurrence],
) -> DocumentLocator | _LocatorWithYear:
    """Return a locator view annotated with the occurrence's filing year."""
    year = _filing_year_for(matching_occs)
    if year is None:
        return locator
    return _LocatorWithYear(locator, year)


def _persist_exhibit(
    exhibit_payload: bytes,
    exhibit_path: str,
    primary_locator: DocumentLocator,
    processor: DocumentProcessor,
    executor,
    payload_sink: Callable[[object, str, bytes], None] | None,
) -> str | None:
    """Persist one exhibit sub-document as its own blob + normalized row.

    Returns the exhibit ``doc_id`` on success, ``None`` on failure. Failures
    land in ``normalization_failures`` with an ``exhibit_refetch:`` prefix and
    never silently drop (per the worker contract).
    """
    exhibit_locator = DocumentLocator(
        locator_key=f"{primary_locator.accession}:{exhibit_path}",
        accession=primary_locator.accession,
        document_path=exhibit_path,
        archive_url="",
        form=primary_locator.form,
    )
    exhibit_doc_id = doc_id(exhibit_locator.accession, exhibit_locator.document_path)
    try:
        if payload_sink is not None:
            payload_sink(executor, exhibit_doc_id, exhibit_payload)
        blob = build_blob(
            exhibit_locator.accession, exhibit_locator.document_path, exhibit_payload
        )
        executor.exec(
            executor.compiler.compile(
                insert_values(
                    DOCUMENT_BLOBS_TABLE,
                    blob.to_row(),
                    on_conflict=DoNothing(),
                )
            )
        )
        processed = execute_processor(processor, exhibit_payload, exhibit_locator)
        normalized = NormalizedDocument(
            normalized_artifact_id=normalized_artifact_id(
                blob.raw_payload_sha256, processed.processor_fingerprint
            ),
            source_doc_id=exhibit_doc_id,
            byte_size=processed.byte_size,
            normalized_payload=compress_payload(processed.payload),
            payload_sha256=hashlib.sha256(processed.payload).hexdigest(),
            mime_type=processed.mime_type,
            representation=processed.representation,
            processor_fingerprint=processed.processor_fingerprint,
            schema_version=NORMALIZED_SCHEMA_VERSION,
            processor_metadata=deterministic_metadata(processed.metadata),
        )
        executor.exec(
            executor.compiler.compile(
                insert_values(
                    NORMALIZED_DOCUMENTS_TABLE,
                    normalized.to_row(),
                    on_conflict=DoNothing(),
                )
            )
        )
        return exhibit_doc_id
    except Exception as exc:  # noqa: BLE001 - failures are durable records
        failure = NormalizationFailure(
            source_doc_id=exhibit_doc_id,
            processor_fingerprint=getattr(
                processor, "processor_fingerprint", "custom:unspecified"
            ),
            schema_version=NORMALIZED_SCHEMA_VERSION,
            error_message=f"{EXHIBIT_REFETCH_ERROR_PREFIX}{exc or type(exc).__name__}",
            attempted_at=datetime.now(UTC).isoformat(),
        )
        executor.exec(
            executor.compiler.compile(
                insert_values(
                    NORMALIZATION_FAILURES_TABLE,
                    failure.to_row(),
                    on_conflict=DoNothing(),
                )
            )
        )
        return None


def run_exhibit_second_pass(
    processed: Any,
    primary_locator: DocumentLocator,
    source_bundle: bytes | None,
    fetcher: Any,
    processor: DocumentProcessor,
    executor,
    payload_sink: Callable[[object, str, bytes], None] | None,
) -> str | None:
    """Resolve and persist the evaluator-targeted exhibit after a stub decision.

    Bounded: one in-bundle attempt plus at most one bundle fetch. Returns the
    exhibit ``doc_id`` or ``None``.
    """
    metadata = getattr(processed, "metadata", {}) or {}
    if metadata.get("decision_action") != "refetch_sub_doc":
        return None
    target_exhibit = metadata.get("target_exhibit")
    if not target_exhibit:
        return None

    bundle = source_bundle
    if bundle is None:
        with suppress(ValueError):
            canonical = normalize_accession(primary_locator.accession)
            if canonical is None:
                return None
            bundle_locator = DocumentLocator(
                locator_key=f"{primary_locator.accession}:full-submission",
                accession=primary_locator.accession,
                document_path=f"{accession_hyphenated(canonical)}.txt",
                archive_url="",
                form=primary_locator.form,
            )
            bundle_result = fetcher.fetch(bundle_locator)
            if bundle_result.status == "ok" and bundle_result.payload is not None:
                candidate = bundle_result.source_payload or bundle_result.payload
                if has_sgml_documents(candidate):
                    bundle = candidate
    if bundle is None:
        return None

    exhibit_payload, exhibit_filename = locate_sub_document_with_filename(
        bundle, (str(target_exhibit),)
    )
    if exhibit_payload is None:
        return None

    # Prefer the exhibit's own <FILENAME>; fall back to a synthetic path.
    if exhibit_filename:
        exhibit_path = exhibit_filename
    else:
        exhibit_path = (
            f"{primary_locator.accession}-"
            f"{str(target_exhibit).lower().replace('/', '-')}.txt"
        )

    return _persist_exhibit(
        exhibit_payload,
        exhibit_path,
        primary_locator,
        processor,
        executor,
        payload_sink,
    )


def annotate_primary_exhibit_link(
    executor,
    primary_artifact_id: str,
    metadata: Mapping[str, object],
    exhibit_doc_id: str,
) -> None:
    """Rewrite the primary row's processor_metadata to link its exhibit.

    Metadata is already deterministic JSON; re-serializing with the link key
    preserves key ordering and keeps the row self-describing.
    """
    linked = dict(metadata)
    linked["exhibit_doc_id"] = exhibit_doc_id
    executor.exec(
        executor.compiler.compile(
            Update.from_mapping(
                NORMALIZED_DOCUMENTS_TABLE,
                {"processor_metadata": deterministic_metadata(linked)},
                where=Compare(
                    col("normalized_artifact_id"),
                    ComparisonOp.EQ,
                    param(primary_artifact_id),
                ),
            )
        )
    )


__all__ = [
    "EXHIBIT_REFETCH_ERROR_PREFIX",
    "annotate_primary_exhibit_link",
    "run_exhibit_second_pass",
    "with_filing_year",
]
