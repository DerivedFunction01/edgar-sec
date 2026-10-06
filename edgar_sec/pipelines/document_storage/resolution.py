"""Pure filing-resolution contract: map a catalog-requested document to an optional primary.

No fetching, persistence, normalization, or publishing; no schema or checkpoint change.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence

from urllib.parse import urlparse

from edgar_sec.domain.document.acquisition import (
    AcquisitionSource,
    BundleFetchResult,
    DocumentReference,
    FilingResolutionOutcome,
    FilingResolutionResult,
    SubmissionDocument,
    unresolved_resolution,
)
from edgar_sec.domain.document.models import (
    derive_occurrence_id,
    DocumentLocator,
    DocumentPathSource,
    FilingOccurrence,
)
from edgar_sec.domain.forms.common.aliases import (
    FORM_FAMILY_ALIASES,
    aliases_for_family,
    form_family,
)
from edgar_sec.engine.document.unpacking.unpacker import (
    _ResolvedDocument,
    has_sgml_documents,
    scan_filing_bundle,
)
from edgar_sec.pipelines.document_storage.candidates import (
    CandidateIntent,
    candidate_for,
)

__all__ = [
    "resolve_candidate_filing",
]


def _accepted_type_set(form: str | None) -> Collection[str]:
    """The accepted <TYPE> tokens derived from the raw submitted form.

    The submitted token, its canonical family, family aliases, and the amendment
    counterpart. For an unknown form, only the submitted token and ``/A`` count.
    """
    if not form:
        return ()
    upper = form.strip().upper()
    family = form_family(form)
    if family in FORM_FAMILY_ALIASES:
        return (upper, family, *aliases_for_family(family))
    return (upper, f"{upper}/A")


def _archive_url(source: AcquisitionSource | None, fallback: str | None) -> str | None:
    """Prefer the bundle source URL when it parses, else the requested locator's URL."""
    if source is not None and source.reference:
        candidate = urlparse(source.reference)
        if candidate.scheme:
            return source.reference
    if fallback:
        candidate = urlparse(fallback)
        if candidate.scheme:
            return fallback
    return None


def _is_valid_basename(path: str | None) -> bool:
    """Return whether ``path`` is a safe plain filename for a recovered primary.

    Rejects empty, path-qualified, ``.``/``..``, and NUL-containing names.
    """
    if not path:
        return False
    normalized = path.strip()
    if not normalized or normalized in (".", ".."):
        return False
    if "/" in normalized or "\\" in normalized or "\x00" in normalized:
        return False
    return True


def _reference_from_resolved(
    resolved: _ResolvedDocument,
    locator: DocumentLocator,
    source: AcquisitionSource | None,
    *,
    document_path_source: DocumentPathSource | None = None,
) -> DocumentReference:
    """Turn a scanned, body-carrying descriptor into a ``DocumentReference``.

    The recovered primary's locator is rebuilt from the bundle header fields; its key
    is recomputed from accession and filename.
    """
    url = _archive_url(source, locator.archive_url)
    new_locator = DocumentLocator.from_parts(
        accession=locator.accession,
        document_path=resolved.document_path or "",
        archive_url=url,
        form=locator.form,
        source_cik=locator.source_cik,
        document_type=resolved.doc_type,
        document_path_source=document_path_source,
    )
    return DocumentReference(
        locator=new_locator,
        descriptor=SubmissionDocument(
            document_path=resolved.document_path,
            content_route=resolved.content_route,
            sequence=resolved.sequence,
            doc_type=resolved.doc_type,
            description=resolved.description,
        ),
        payload=resolved.payload,
        source=source,
    )


def resolve_candidate_filing(
    requested: DocumentReference,
    occurrences: Sequence[FilingOccurrence],
    bundle_result: BundleFetchResult,
) -> FilingResolutionResult:
    """Resolve a catalog-requested document plus an optional recovered primary.

    ``occurrences`` is never mutated; no fetch, persist, normalize, or publish, and
    malformed source data returns outcome flags rather than exceptions.
    """
    # Gate: the advisory policy must explicitly authorize bundle inspection.
    _, decision = candidate_for(requested.locator, occurrences)
    if decision.intent is not CandidateIntent.BUNDLE_CANDIDATE:
        # A request already named like the primary form is allowed through: there is
        # no inversion to perform, only an identity check (REQUESTED_IS_PRIMARY).
        if not (
            decision.intent is CandidateIntent.WINDOW_ELIGIBLE
            and decision.reason == "primary_form_token"
        ):
            return unresolved_resolution(
                requested=requested,
                occurrences=occurrences,
                outcome=FilingResolutionOutcome.NOT_CANDIDATE,
            )

    # The bundle must have been acquired.
    if bundle_result.status != "ok" or bundle_result.payload is None:
        return unresolved_resolution(
            requested=requested,
            occurrences=occurrences,
            outcome=FilingResolutionOutcome.BUNDLE_UNAVAILABLE,
        )

    # The bundle must be an SGML envelope.
    if not has_sgml_documents(bundle_result.payload):
        return unresolved_resolution(
            requested=requested,
            occurrences=occurrences,
            outcome=FilingResolutionOutcome.NON_SGML_BUNDLE,
        )

    # Parse headers and slice only the retained bodies.
    accepted_types = _accepted_type_set(requested.locator.form)
    scan = scan_filing_bundle(
        bundle_result.payload,
        requested.locator.document_path,
        accepted_types,
    )

    # Structural problems are a normal outcome, not an exception.
    if scan.scan_error:
        return unresolved_resolution(
            requested=requested,
            occurrences=occurrences,
            outcome=FilingResolutionOutcome.MALFORMED_SGML,
        )

    # The requested document must appear exactly once by basename.
    if scan.requested_match_count == 0:
        return unresolved_resolution(
            requested=requested,
            occurrences=occurrences,
            outcome=FilingResolutionOutcome.REQUESTED_NOT_IN_BUNDLE,
        )
    if scan.requested_match_count >= 2:
        return unresolved_resolution(
            requested=requested,
            occurrences=occurrences,
            outcome=FilingResolutionOutcome.AMBIGUOUS_HEADERS,
        )

    # Acceptable primary types must exist.
    accepted = {t.strip().upper() for t in accepted_types}
    matching = [
        d for d in scan.documents if d.doc_type and d.doc_type.upper() in accepted
    ]
    if not matching:
        return unresolved_resolution(
            requested=requested,
            occurrences=occurrences,
            outcome=FilingResolutionOutcome.NO_MATCHING_PRIMARY,
        )

    # Ordering metadata must identify a unique lowest sequence.
    if scan.primary_sequence_tie or scan.primary_invalid_sequence:
        return unresolved_resolution(
            requested=requested,
            occurrences=occurrences,
            outcome=FilingResolutionOutcome.AMBIGUOUS_HEADERS,
        )
    if scan.primary is None:
        return unresolved_resolution(
            requested=requested,
            occurrences=occurrences,
            outcome=FilingResolutionOutcome.AMBIGUOUS_HEADERS,
        )

    # Adopt the bundle's descriptor and body for the requested reference.
    assert scan.requested is not None
    requested_ref = DocumentReference(
        locator=requested.locator,
        descriptor=SubmissionDocument(
            document_path=scan.requested.document_path,
            content_route=scan.requested.content_route,
            sequence=scan.requested.sequence,
            doc_type=scan.requested.doc_type,
            description=scan.requested.description,
        ),
        payload=scan.requested.payload,
        source=bundle_result.source,
    )

    # The primary candidate is the requested document itself.
    primary_filename = scan.primary.document_path or ""
    requested_filename = scan.requested.document_path or ""
    if primary_filename.lower() == requested_filename.lower():
        return FilingResolutionResult(
            requested=requested_ref,
            requested_occurrences=occurrences,
            primary=requested_ref,
            outcome=FilingResolutionOutcome.REQUESTED_IS_PRIMARY,
        )

    # A distinct document is the recovered primary; the request is the exhibit.
    if not _is_valid_basename(primary_filename):
        return unresolved_resolution(
            requested=requested_ref,
            occurrences=occurrences,
            outcome=FilingResolutionOutcome.MALFORMED_SGML,
        )

    # Validate source CIKs: a missing CIK takes precedence over a duplicate one.
    ciks: list[str] = []
    for occurrence in occurrences:
        if occurrence.source_cik is None:
            return unresolved_resolution(
                requested=requested_ref,
                occurrences=occurrences,
                outcome=FilingResolutionOutcome.MISSING_SOURCE_CIK,
            )
        cik = occurrence.source_cik.to_10digit()
        if cik in ciks:
            return unresolved_resolution(
                requested=requested_ref,
                occurrences=occurrences,
                outcome=FilingResolutionOutcome.DUPLICATE_SOURCE_CIK,
            )
        ciks.append(cik)

    primary = _reference_from_resolved(
        scan.primary,
        requested.locator,
        bundle_result.source,
        document_path_source=DocumentPathSource.RECOVERED_SUBMISSION_BUNDLE,
    )
    primary_occurrences = tuple(
        FilingOccurrence(
            occurrence_id=derive_occurrence_id(
                occurrence.source_cik.to_10digit(),
                str(primary.locator.accession),
                primary.locator.document_path,
            ),
            source_cik=occurrence.source_cik,
            accession=primary.locator.accession,
            document_path=primary.locator.document_path,
            form=occurrence.form,
            filing_date=occurrence.filing_date,
            report_date=occurrence.report_date,
            doc_id=primary.locator.document_locator_key,
        )
        for occurrence in occurrences
    )
    return FilingResolutionResult(
        requested=requested_ref,
        requested_occurrences=occurrences,
        primary=primary,
        exhibit=requested_ref,
        primary_occurrences=primary_occurrences,
        outcome=FilingResolutionOutcome.PRIMARY_RECOVERED,
    )
