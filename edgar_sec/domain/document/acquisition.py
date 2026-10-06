"""Domain records for a document acquisition attempt.

A *locator* naming a document lives in :mod:`edgar_sec.domain.document.models`; a fetcher
may name a document and report on it, but only a pipeline may decide it is worth keeping.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal

from edgar_sec.domain.document.models import (
    derive_occurrence_id,
    DocumentLocator,
    DocumentPathSource,
    FilingOccurrence,
)
from edgar_sec.domain.document.route import DocumentRoute, document_route
from edgar_sec.domain.identity import AccessionNumber

FetchStatus = Literal["ok", "missing", "failed"]

#: Complete submission bundle filenames look like ``0000320193-20-000096.txt``.
#: Matched as a pattern, not a suffix: every bundle name also ends in a stub sequence
#: suffix, so a literal comparison would call every bundle a stub.
_BUNDLE_NAME_RE = re.compile(r"\d{10}-\d{2}-\d{6}\.txt$")

#: Accession sequence suffixes that mark a placeholder primary document.
_STUB_SEQUENCE_SUFFIXES = ("0001.txt", "0001.htm", "0000.txt", "0000.htm")


def is_stub_document_path(document_path: str | None) -> bool:
    """Return whether a document path is a stub rather than substantive content.

    Complete submission bundle paths are real targets and are never stubs,
            even when the accession's sequence ends in ``0000``/``0001``.
    """
    if not document_path:
        return True
    lowered = document_path.strip().lower()
    if _BUNDLE_NAME_RE.search(lowered):
        return False
    return lowered.endswith(_STUB_SEQUENCE_SUFFIXES)


class AcquisitionSourceKind(StrEnum):
    """What kind of source produced an acquired payload."""

    #: An EDGAR archive URL served over the transport.
    ARCHIVE_URL = "archive_url"
    #: A recorded response replayed from a fixture store.
    FIXTURE = "fixture"


@dataclass(frozen=True, slots=True)
class AcquisitionSource:
    """The exact source that produced a payload, distinct from the requested locator.

    The two differ whenever a rendered link is served from the archive root, so a
    caller that assumes they are equal misreports where its bytes came from.
    """

    kind: AcquisitionSourceKind
    reference: str


class SubmissionFormat(StrEnum):
    """What kind of response one acquisition resolved."""

    #: A single document served at its own URL.
    DIRECT = "direct"
    #: An SGML submission envelope holding several documents.
    SGML = "sgml"


@dataclass(frozen=True, slots=True)
class SubmissionDocument:
    """One document known inside an acquired submission, described but not loaded.

    Observed header facts only, and no body: nothing here asserts the document is a
    filing's primary, or that any sibling is an exhibit.
    """

    document_path: str | None
    content_route: DocumentRoute
    sequence: int | None = None
    doc_type: str | None = None
    description: str | None = None


def describe_submission_document(
    *,
    document_path: str | None,
    content_route: DocumentRoute,
    sequence: int | None = None,
    doc_type: str | None = None,
    description: str | None = None,
) -> SubmissionDocument:
    """Normalize one observed header into a descriptor.

    An absent filename is recorded as absent rather than guessed, and the caller's
    route is preserved: deciding a route from content is a separate decision.
    """
    return SubmissionDocument(
        document_path=document_path.strip() if document_path else None,
        content_route=content_route,
        sequence=sequence,
        doc_type=doc_type,
        description=description,
    )


@dataclass(frozen=True, slots=True)
class AcquiredSubmission:
    """One successful acquisition, scoped to the accession its locator names.

    Every known document is described and exactly one body is loaded. No full source
    envelope is retained; ``selected_index`` is the only link to the loaded body.
    """

    requested_locator: DocumentLocator
    source_format: SubmissionFormat
    documents: tuple[SubmissionDocument, ...]
    selected_index: int
    selected_payload: bytes
    source: AcquisitionSource | None = None

    def __post_init__(self) -> None:
        if not self.documents:
            raise ValueError("an acquired submission must describe a document")
        if not 0 <= self.selected_index < len(self.documents):
            raise ValueError("selected_index names no described document")
        if self.source_format is SubmissionFormat.DIRECT and (
            len(self.documents) != 1 or self.selected_index != 0
        ):
            raise ValueError("a direct acquisition describes exactly one document")

    @property
    def accession(self) -> AccessionNumber:
        return self.requested_locator.accession

    @property
    def document_locator_key(self) -> str:
        """The requested document's identity, never the acquired source's."""
        return self.requested_locator.document_locator_key

    @property
    def selected_document(self) -> SubmissionDocument:
        return self.documents[self.selected_index]


def direct_acquisition(
    locator: DocumentLocator,
    payload: bytes,
    *,
    source: AcquisitionSource | None = None,
) -> AcquiredSubmission:
    """Describe a document served at its own URL, with no sibling to report."""
    return AcquiredSubmission(
        requested_locator=locator,
        source_format=SubmissionFormat.DIRECT,
        documents=(
            describe_submission_document(
                document_path=locator.document_path,
                content_route=document_route(locator.document_path),
            ),
        ),
        selected_index=0,
        selected_payload=payload,
        source=source,
    )


@dataclass(frozen=True, slots=True)
class FetchResult:
    """What one acquisition attempt produced.

    ``source_payload`` carries the PEM-stripped SGML bundle when the document was
            selected *from* an envelope. It stays transport data, never model state.
    """

    locator: DocumentLocator
    status: FetchStatus
    acquired: AcquiredSubmission | None = None
    error: str | None = None
    source_payload: bytes | None = None

    def __post_init__(self) -> None:
        succeeded = self.status == "ok"
        if succeeded and self.acquired is None:
            raise ValueError("an ok fetch must carry an acquired submission")
        if not succeeded and self.acquired is not None:
            raise ValueError("an unsuccessful fetch carries no acquired submission")
        if (
            self.acquired is not None
            and self.acquired.requested_locator != self.locator
        ):
            raise ValueError("an acquired submission must name the requested locator")

    @property
    def ok(self) -> bool:
        return self.status == "ok" and self.acquired is not None

    @property
    def byte_size(self) -> int:
        return 0 if self.acquired is None else len(self.acquired.selected_payload)


@dataclass(frozen=True, slots=True)
class AcquisitionFailure:
    """One document that could not be acquired, with enough detail to retry."""

    document_locator_key: str
    accession: str
    document_path: str
    error: str
    status: FetchStatus = "failed"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class BundleFetchResult:
    """What one complete submission-bundle acquisition produced.

    ``payload`` is the raw bundle and ``source`` records what answered; both are
    discarded after resolution. Same ``FetchStatus`` success invariants as ``FetchResult``.
    """

    status: FetchStatus
    payload: bytes | None = None
    source: AcquisitionSource | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        succeeded = self.status == "ok"
        if succeeded and self.payload is None:
            raise ValueError("an ok bundle result must carry a payload")
        if not succeeded and self.payload is not None:
            raise ValueError("an unsuccessful bundle result carries no payload")
        if not succeeded and self.error is None:
            raise ValueError("an unsuccessful bundle result must name an error")


@dataclass(frozen=True, slots=True)
class DocumentReference:
    """One body returned by filing resolution, role-independent by construction.

    ``descriptor`` records observed SGML headers; ``payload`` the retained body;
    ``source`` what served it (may be absent); ``locator`` the role-neutral identity.
    """

    locator: DocumentLocator
    descriptor: SubmissionDocument
    payload: bytes
    source: AcquisitionSource | None = None


class FilingResolutionOutcome(StrEnum):
    """The exhaustive set of filing-resolution outcomes.

    An unresolved outcome means the request was kept but no primary was recovered; it
    is a normal result, not a failure of the already acquired requested document.
    """

    #: The advisory candidate gate did not pass; the bundle was never inspected.
    NOT_CANDIDATE = "not_candidate"
    #: The bundle was unavailable or its acquisition failed.
    BUNDLE_UNAVAILABLE = "bundle_unavailable"
    #: A successful bundle result contained no SGML document marker.
    NON_SGML_BUNDLE = "non_sgml_bundle"
    #: Unbalanced or nested ``<DOCUMENT>`` delimiters.
    MALFORMED_SGML = "malformed_sgml"
    #: No exact requested filename appears in the bundle.
    REQUESTED_NOT_IN_BUNDLE = "requested_not_in_bundle"
    #: No accepted form type appears in the bundle.
    NO_MATCHING_PRIMARY = "no_matching_primary"
    #: Duplicate requested filename, or an accepted type without valid ordering
    #: metadata, or a tie for the lowest accepted sequence.
    AMBIGUOUS_HEADERS = "ambiguous_headers"
    #: The first accepted type match in sequence order is the requested document.
    REQUESTED_IS_PRIMARY = "requested_is_primary"
    #: A different first accepted type match is the recovered primary.
    PRIMARY_RECOVERED = "primary_recovered"
    #: A requested occurrence lacks a source CIK required to project a primary row.
    MISSING_SOURCE_CIK = "missing_source_cik"
    #: Requested occurrences repeat a CIK, so primary rows would share an ID.
    DUPLICATE_SOURCE_CIK = "duplicate_source_cik"


@dataclass(frozen=True, slots=True)
class FilingResolutionResult:
    """One resolved filing: the requested document plus an optional recovered primary.

    ``requested`` is always acquired; ``primary`` and ``exhibit`` are empty for
    unresolved outcomes; ``REQUESTED_IS_PRIMARY`` sets ``primary is requested``.
    """

    requested: DocumentReference
    requested_occurrences: tuple[FilingOccurrence, ...]
    outcome: FilingResolutionOutcome
    primary: DocumentReference | None = None
    exhibit: DocumentReference | None = None
    primary_occurrences: tuple[FilingOccurrence, ...] = ()

    def __post_init__(self) -> None:
        # Freeze both occurrence sequences so later mutation cannot break
        # the correspondence between requested and projected rows.
        object.__setattr__(
            self, "requested_occurrences", tuple(self.requested_occurrences)
        )
        object.__setattr__(self, "primary_occurrences", tuple(self.primary_occurrences))

        unresolved = {
            FilingResolutionOutcome.NOT_CANDIDATE,
            FilingResolutionOutcome.BUNDLE_UNAVAILABLE,
            FilingResolutionOutcome.NON_SGML_BUNDLE,
            FilingResolutionOutcome.MALFORMED_SGML,
            FilingResolutionOutcome.REQUESTED_NOT_IN_BUNDLE,
            FilingResolutionOutcome.NO_MATCHING_PRIMARY,
            FilingResolutionOutcome.AMBIGUOUS_HEADERS,
        }
        if self.outcome in unresolved:
            if self.primary is not None or self.exhibit is not None:
                raise ValueError(
                    "an unresolved outcome carries neither primary nor exhibit"
                )
        elif self.outcome is FilingResolutionOutcome.MISSING_SOURCE_CIK:
            if self.primary is not None or self.exhibit is not None:
                raise ValueError(
                    "MISSING_SOURCE_CIK carries neither primary nor exhibit"
                )
        elif self.outcome is FilingResolutionOutcome.DUPLICATE_SOURCE_CIK:
            if self.primary is not None or self.exhibit is not None:
                raise ValueError(
                    "DUPLICATE_SOURCE_CIK carries neither primary nor exhibit"
                )
        elif self.outcome is FilingResolutionOutcome.REQUESTED_IS_PRIMARY:
            if self.primary is not self.requested:
                raise ValueError("REQUESTED_IS_PRIMARY requires primary is requested")
            if self.exhibit is not None:
                raise ValueError("REQUESTED_IS_PRIMARY carries no exhibit")
            if self.primary_occurrences:
                raise ValueError("REQUESTED_IS_PRIMARY carries no primary occurrences")
        elif self.outcome is FilingResolutionOutcome.PRIMARY_RECOVERED:
            if self.exhibit is not self.requested or self.primary is None:
                raise ValueError(
                    "PRIMARY_RECOVERED requires exhibit is requested and a distinct primary"
                )
            if self.primary.locator.accession != self.requested.locator.accession:
                raise ValueError("a recovered primary must name the same accession")
            if (
                self.primary.locator.document_locator_key
                == self.requested.locator.document_locator_key
            ):
                raise ValueError("a recovered primary must have a distinct locator key")
            self._validate_primary_occurrences()
        else:
            raise ValueError(f"unknown FilingResolutionOutcome: {self.outcome!r}")

    def _validate_primary_occurrences(self) -> None:
        """Ensure projected primary rows are complete, unique, and deterministic."""
        if len(self.primary_occurrences) != len(self.requested_occurrences):
            raise ValueError(
                "a primary occurrence must project exactly one row per requested occurrence"
            )
        primary = self.primary.locator
        seen_ciks: set[str] = set()
        for requested, projected in zip(
            self.requested_occurrences, self.primary_occurrences
        ):
            cik = projected.source_cik.to_10digit()
            if cik in seen_ciks:
                raise ValueError(
                    "projected primary occurrences must derive distinct occurrence ids"
                )
            seen_ciks.add(cik)
            if (
                projected.source_cik != requested.source_cik
                or projected.accession != primary.accession
                or projected.document_path != primary.document_path
            ):
                raise ValueError(
                    "a projected primary occurrence must not retarget identity"
                )
            if (
                projected.form != requested.form
                or projected.filing_date != requested.filing_date
                or projected.report_date != requested.report_date
            ):
                raise ValueError(
                    "a projected primary occurrence must inherit the source metadata"
                )
            expected_id = derive_occurrence_id(
                cik, str(primary.accession), primary.document_path
            )
            if projected.occurrence_id != expected_id:
                raise ValueError(
                    "a projected primary occurrence id is not deterministic"
                )
            if projected.doc_id != primary.document_locator_key:
                raise ValueError(
                    "a projected primary occurrence must key on the primary locator"
                )
        if (
            primary.document_path_source
            is not DocumentPathSource.RECOVERED_SUBMISSION_BUNDLE
        ):
            raise ValueError(
                "a recovered primary locator must record recovered-bundle provenance"
            )


def unresolved_resolution(
    requested: DocumentReference,
    occurrences: Sequence[FilingOccurrence],
    outcome: FilingResolutionOutcome,
) -> FilingResolutionResult:
    """Build a resolution that kept the request but recovered no primary."""
    if outcome is FilingResolutionOutcome.PRIMARY_RECOVERED:
        raise ValueError("use the full constructor for PRIMARY_RECOVERED")
    return FilingResolutionResult(
        requested=requested,
        requested_occurrences=tuple(occurrences),
        primary_occurrences=(),
        outcome=outcome,
    )


__all__ = [
    "AcquiredSubmission",
    "AcquisitionFailure",
    "AcquisitionSource",
    "AcquisitionSourceKind",
    "BundleFetchResult",
    "DocumentReference",
    "FetchResult",
    "FetchStatus",
    "FilingResolutionOutcome",
    "FilingResolutionResult",
    "MISSING_SOURCE_CIK",
    "DUPLICATE_SOURCE_CIK",
    "SubmissionDocument",
    "SubmissionFormat",
    "describe_submission_document",
    "direct_acquisition",
    "is_stub_document_path",
    "unresolved_resolution",
]
