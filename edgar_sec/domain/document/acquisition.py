"""Domain records for a document acquisition attempt.

A *locator* naming a document lives in :mod:`edgar_sec.domain.document.models`; a fetcher
may name a document and report on it, but only a pipeline may decide it is worth keeping.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal

from edgar_sec.domain.document.models import DocumentLocator
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


__all__ = [
    "AcquiredSubmission",
    "AcquisitionFailure",
    "AcquisitionSource",
    "AcquisitionSourceKind",
    "FetchResult",
    "FetchStatus",
    "SubmissionDocument",
    "SubmissionFormat",
    "describe_submission_document",
    "direct_acquisition",
    "is_stub_document_path",
]
