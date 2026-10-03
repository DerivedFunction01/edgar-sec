"""Domain records for a document acquisition attempt.

A *locator* naming a document lives in :mod:`edgar_sec.domain.document.models`; a fetcher
may name a document and report on it, but only a pipeline may decide it is worth keeping.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

from edgar_sec.domain.document.models import DocumentLocator

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

    @property
    def ok(self) -> bool:
        return self.status == "ok" and self.payload is not None

    @property
    def byte_size(self) -> int:
        return 0 if self.payload is None else len(self.payload)


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
    "AcquisitionFailure",
    "FetchResult",
    "FetchStatus",
    "is_stub_document_path",
]
