"""The exhibit second pass: fetch what a stub decision delegated.

Bounded on purpose: one attempt against a held bundle, at most one bundle fetch. An
unresolvable delegation stays unresolved, so a bad document cannot stall the run.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from edgar_sec.domain.document.models import (
    DocumentLocator,
    derive_document_locator_key,
    derive_occurrence_id,
)
from edgar_sec.domain.identity import AccessionNumber, Cik
from edgar_sec.domain.sec_urls import accession_hyphenated, normalize_accession
from edgar_sec.engine.document.unpacking.unpacker import (
    SgmlSubDocument,
    find_sub_document,
    has_sgml_documents,
    unpack_sgml_submission,
)
from edgar_sec.pipelines.document_storage.fetching import ArchiveFetcher
from edgar_sec.pipelines.document_storage.processor import (
    DocumentProcessor,
    ProcessedDocument,
)

log = logging.getLogger("document_storage.delegation")

REFETCH_ACTION = "refetch_sub_doc"


@dataclass(frozen=True, slots=True)
class DelegatedExhibit:
    """An exhibit resolved from a stub primary's delegation decision.

    Primary accession and CIK are carried here rather than re-read from free-form
    metadata, which would tie snapshot correctness to dict key spelling.
    """

    document_locator_key: str
    document_path: str
    target_exhibit: str
    processed: ProcessedDocument
    source: str
    primary_accession: AccessionNumber
    primary_form: str
    primary_source_cik: str
    primary_document_locator_key: str

    @property
    def byte_size(self) -> int:
        return self.processed.byte_size

    @property
    def occurrence_id(self) -> str:
        """Provenance row identity linking this exhibit to its primary.

        Keyed on the *exhibit's* path, not the primary's: the row must identify the
        exhibit the catalog will carry.
        """
        return derive_occurrence_id(
            self.primary_source_cik,
            str(self.primary_accession),
            self.document_path,
        )


def _bundle_locator(primary: DocumentLocator) -> DocumentLocator | None:
    """Return the locator for the primary's full submission bundle."""
    canonical = normalize_accession(str(primary.accession))
    if canonical is None:
        return None
    bundle_path = f"{accession_hyphenated(canonical)}.txt"
    return DocumentLocator.from_parts(
        str(primary.accession),
        bundle_path,
        form=primary.form,
        source_cik=primary.source_cik,
    )


def _exhibit_aliases(target: str) -> tuple[str, ...]:
    """Return the sub-document types naming one exhibit, normalized to upper case."""
    return (target.strip().upper(),)


def _select_exhibit(bundle: bytes, target_exhibit: str) -> SgmlSubDocument | None:
    """Find the target exhibit inside one SGML bundle."""
    if not has_sgml_documents(bundle):
        return None
    sub_docs = unpack_sgml_submission(bundle)
    return find_sub_document(sub_docs, target_types=_exhibit_aliases(target_exhibit))


def _exhibit_path(
    primary: DocumentLocator, sub_doc: SgmlSubDocument, target: str
) -> str:
    """Return the stored path for a resolved exhibit."""
    if sub_doc.filename.strip():
        return sub_doc.filename.strip()
    safe = str(target).strip().lower().replace("/", "-")
    return f"{primary.accession}-{safe}.txt"


def resolve_delegated_exhibit(
    processed: ProcessedDocument,
    primary: DocumentLocator,
    *,
    fetcher: ArchiveFetcher,
    processor: DocumentProcessor,
    source_bundle: bytes | None = None,
    payload_sink: Callable[[DocumentLocator, bytes], None] | None = None,
) -> DelegatedExhibit | None:
    """Resolve and process the exhibit a stub decision delegated to.

    Returns ``None`` when the decision was not a refetch, names no exhibit, or the
    exhibit is unresolvable inside the one-fetch budget.
    """
    metadata = processed.metadata or {}
    if metadata.get("decision_action") != REFETCH_ACTION:
        return None
    target = metadata.get("target_exhibit")
    if not target:
        return None
    target_text = str(target)

    bundle = source_bundle
    source = "in-bundle"
    if bundle is None:
        bundle_locator = _bundle_locator(primary)
        if bundle_locator is None:
            return None
        with suppress(Exception):
            bundle_result = fetcher.fetch(bundle_locator)
            if bundle_result.ok:
                candidate = bundle_result.source_payload or bundle_result.payload
                if candidate is not None and has_sgml_documents(candidate):
                    bundle = candidate
                    source = "bundle-fetch"
    if bundle is None:
        log.info("no bundle available for %s", primary.document_locator_key)
        return None

    sub_doc = _select_exhibit(bundle, target_text)
    if sub_doc is None:
        log.info(
            "exhibit %s not present in bundle for %s",
            target_text,
            primary.document_locator_key,
        )
        return None

    document_path = _exhibit_path(primary, sub_doc, target_text)
    exhibit_locator = DocumentLocator.from_parts(
        str(primary.accession),
        document_path,
        form=primary.form,
        source_cik=primary.source_cik,
        document_type=target_text,
    )
    if payload_sink is not None:
        payload_sink(exhibit_locator, sub_doc.raw_payload)

    exhibit_processed = processor.process(sub_doc.raw_payload, exhibit_locator)
    exhibit_processed = _annotate_delegation(
        exhibit_processed, primary, target_text, document_path
    )
    return DelegatedExhibit(
        document_locator_key=derive_document_locator_key(
            str(primary.accession), document_path
        ),
        document_path=document_path,
        target_exhibit=target_text,
        processed=exhibit_processed,
        source=source,
        primary_accession=primary.accession,
        primary_form=primary.form or "",
        primary_source_cik=primary.source_cik or "",
        primary_document_locator_key=primary.document_locator_key,
    )


def _annotate_delegation(
    processed: ProcessedDocument,
    primary: DocumentLocator,
    target: str,
    document_path: str,
) -> ProcessedDocument:
    """Attach the primary-to-exhibit link so the snapshot records provenance.

    Otherwise an exhibit row is indistinguishable from a directly requested document.
    """
    from dataclasses import replace

    metadata: dict[str, object] = dict(processed.metadata)
    metadata.update(
        {
            "delegated_from_document_locator_key": primary.document_locator_key,
            "delegated_from_accession": str(primary.accession),
            "delegated_from_form": primary.form,
            "delegated_from_source_cik": primary.source_cik or "",
            "target_exhibit": target,
            "delegated_exhibit_path": document_path,
        }
    )
    return replace(processed, metadata=metadata)


def exhibits_for(
    primary_document_locator_key: str,
    exhibits: Mapping[str, DelegatedExhibit],
) -> tuple[DelegatedExhibit, ...]:
    """Return the exhibits delegated to by one primary."""
    return tuple(
        exhibit
        for exhibit in exhibits.values()
        if exhibit.primary_document_locator_key == primary_document_locator_key
    )


def write_exhibit_snapshot(
    output_path: Path, exhibits: tuple[DelegatedExhibit, ...]
) -> Path:
    """Publish resolved exhibits as a Parquet file with the checkpoint schema.

    Same schema as a chunk, so a later merge needs no separate reader.
    """
    from edgar_sec.domain.document.models import FilingOccurrence
    from edgar_sec.pipelines.document_storage.checkpoint import write_chunk_snapshot

    occurrences: list[FilingOccurrence] = []
    raw_blobs: dict[str, bytes] = {}
    texts: dict[str, str] = {}
    statuses: dict[str, str] = {}
    for exhibit in exhibits:
        occurrence = FilingOccurrence(
            occurrence_id=exhibit.occurrence_id,
            source_cik=Cik.from_raw(exhibit.primary_source_cik or "0"),
            accession=exhibit.primary_accession,
            document_path=exhibit.document_path,
            form=exhibit.primary_form,
            filing_date="",
            report_date=None,
            doc_id=exhibit.document_locator_key,
        )
        occurrences.append(occurrence)
        raw_blobs[exhibit.document_locator_key] = exhibit.processed.payload
        texts[occurrence.occurrence_id] = exhibit.processed.text
        statuses[occurrence.occurrence_id] = "ok"

    write_chunk_snapshot(output_path, occurrences, raw_blobs, texts, statuses, {})
    return Path(output_path)


__all__ = [
    "REFETCH_ACTION",
    "DelegatedExhibit",
    "exhibits_for",
    "resolve_delegated_exhibit",
    "write_exhibit_snapshot",
]
