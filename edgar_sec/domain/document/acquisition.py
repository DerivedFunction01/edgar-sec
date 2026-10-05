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
from edgar_sec.domain.document.route import DocumentRoute, content_route, document_route

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


@dataclass(frozen=True, slots=True)
class SgmlSubDocumentHeader:
    """One SGML sub-document's header facts, without its payload.

    Observed facts only: nothing here asserts the sub-document is a filing's primary
    document, or that any sibling is an exhibit.
    """

    sequence: int | None
    doc_type: str
    filename: str
    description: str | None


@dataclass(frozen=True, slots=True)
class SgmlEnvelopeResolution:
    """The selected sub-document of an SGML envelope, plus its siblings.

    ``siblings`` excludes the selected document and keeps envelope order. No sibling
    carries bytes, so resolving one document never materializes a whole submission.
    """

    selected: SgmlSubDocumentHeader
    siblings: tuple[SgmlSubDocumentHeader, ...]


@dataclass(frozen=True, slots=True)
class AcquiredDocument:
    """One requested locator's payload, and how it resolved.

    Carries no source envelope: that spans the whole submission, and only the selected
    sub-document is needed.
    """

    locator: DocumentLocator
    payload: bytes
    content_route: DocumentRoute
    source: AcquisitionSource | None = None
    envelope: SgmlEnvelopeResolution | None = None

    @property
    def document_locator_key(self) -> str:
        """The requested document's identity, never the acquired source's."""
        return self.locator.document_locator_key


@dataclass(frozen=True, slots=True)
class FetchResult:
    """What one acquisition attempt produced.

    ``source_payload`` carries the PEM-stripped SGML bundle when the payload was
            selected *from* an envelope, so in-bundle exhibits resolve without a refetch.
    """

    locator: DocumentLocator
    payload: bytes | None
    status: FetchStatus
    error: str | None = None
    source_payload: bytes | None = None
    source: AcquisitionSource | None = None
    envelope: SgmlEnvelopeResolution | None = None

    @property
    def ok(self) -> bool:
        return self.status == "ok" and self.payload is not None

    @property
    def byte_size(self) -> int:
        return 0 if self.payload is None else len(self.payload)

    @property
    def acquired(self) -> AcquiredDocument | None:
        """This fetch as an acquired document, or ``None`` when it did not succeed.

        The route follows the bytes: a selected sub-document carries its own filename.
        """
        if self.payload is None or self.status != "ok":
            return None
        route = (
            content_route(self.envelope.selected.filename)
            if self.envelope is not None
            else document_route(self.locator.document_path)
        )
        return AcquiredDocument(
            locator=self.locator,
            payload=self.payload,
            content_route=route,
            source=self.source,
            envelope=self.envelope,
        )


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
    "AcquiredDocument",
    "AcquisitionFailure",
    "AcquisitionSource",
    "AcquisitionSourceKind",
    "FetchResult",
    "FetchStatus",
    "SgmlEnvelopeResolution",
    "SgmlSubDocumentHeader",
    "is_stub_document_path",
]
