"""Domain models for content-addressed document locators, occurrences, and blobs."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

from edgar_sec.domain.identity import AccessionNumber, Cik
from edgar_sec.foundation.hashing import sha256_text


class DocumentKind(StrEnum):
    """Document format classification."""

    HTML = "html"
    ASCII_TXT = "ascii_txt"
    XML = "xml"


def canonical_accession_part(accession: str) -> str:
    """Return the hyphen-free accession used inside every content-addressed digest.

    The catalog materialises ``accession`` as ``replace(accession_number, '-', '')``
    and hashes that unhyphenated column. A caller holding the hyphenated EDGAR
    spelling (``0000320193-23-000106``) must therefore be reduced to the same string
    before hashing, or its key silently matches nothing on disk.

    Unparseable input is returned with hyphens merely stripped rather than
    rejected: this is a digest input, not a validation boundary, and a malformed
    accession should still hash deterministically and fail at the point of use
    rather than here.
    """
    return str(accession).strip().replace("-", "")


def derive_document_locator_key(accession: str, document_path: str) -> str:
    """Generate deterministic content-addressed key for an accession + document path pair.

    Must stay byte-identical to the SQL spelling in
    ``infra/storage/duckdb_catalog.py``:
    ``sha256(accession || ':' || document_path)`` over the *unhyphenated*
    ``accession`` column. The catalog materialises locator keys inside DuckDB
    while this module derives them in Python, and a locator join between the two
    worlds is how a published snapshot is read back. Both spellings of an accession
    are reduced by :func:`canonical_accession_part` first, because
    EDGAR serves the hyphenated and unhyphenated forms interchangeably and the
    two must not produce two identities for one document.
    ``tests/foundation/test_hashing.py`` pins the byte equality.
    """
    return sha256_text(f"{canonical_accession_part(accession)}:{document_path.strip()}")


def derive_occurrence_id(source_cik: str, accession: str, document_path: str) -> str:
    """Generate deterministic occurrence identifier linking a CIK to a document.

    Must stay byte-identical to the SQL spelling in
    ``infra/storage/duckdb_catalog.py``:
    ``sha256(source_cik || ':' || accession || ':' || document_path)`` over the
    *unhyphenated* ``accession`` column, so the accession part is reduced by
    :func:`canonical_accession_part` exactly as the locator key is.

    The three **raw parts**, not a derived key: hashing the locator key
    would be a hash of a hash, and the SQL side hashes the raw parts. A locator
    key therefore has to stay byte-identical between the two worlds, or a
    locator-to-occurrence join between the catalog and a snapshot matches nothing,
    silently.
    """
    return sha256_text(
        f"{source_cik.strip()}:{canonical_accession_part(accession)}:"
        f"{document_path.strip()}"
    )


@dataclass(frozen=True, slots=True)
class DocumentLocator:
    """Content-addressed reference to a filing document, plus how to acquire it.

    ``document_locator_key`` is the canonical identity of the document and is
    derived from accession plus path, never supplied independently: the payload
    store, the fetchers, and the Parquet snapshot all key on it, so a locator
    that disagreed with its own key would silently split one document across
    two identities.

    The acquisition fields are optional because not every caller can reach the
    network: a replay from a fixture needs only the key.

    ``accession`` accepts either EDGAR spelling and is held in the hyphenated
    form. Catalog plans and fixture rows carry the unhyphenated
    ``000032019323000106``, and rejecting that would make a real plan
    unloadable, so it is normalized here rather than refused. The locator key
    is unaffected either way because both spellings hash to one identity.
    """

    accession: AccessionNumber
    document_path: str
    document_locator_key: str
    archive_url: str | None = None
    form: str | None = None
    source_cik: str | None = None
    document_type: str | None = None

    @classmethod
    def from_parts(
        cls,
        accession: AccessionNumber | str,
        document_path: str,
        *,
        archive_url: str | None = None,
        form: str | None = None,
        source_cik: str | None = None,
        document_type: str | None = None,
    ) -> DocumentLocator:
        acc = (
            accession
            if isinstance(accession, AccessionNumber)
            else AccessionNumber.from_any(accession)
        )
        path = document_path.strip()
        key = derive_document_locator_key(str(acc), path)
        return cls(
            accession=acc,
            document_path=path,
            document_locator_key=key,
            archive_url=archive_url,
            form=form,
            source_cik=source_cik,
            document_type=document_type,
        )

    @property
    def is_stub_path(self) -> bool:
        """Whether the path names a placeholder rather than substantive content."""
        from edgar_sec.domain.document.acquisition import is_stub_document_path

        return is_stub_document_path(self.document_path)


@dataclass(frozen=True, slots=True)
class RawDocumentBlob:
    """One content-addressed document metadata record."""

    doc_id: str
    accession: str
    document_path: str
    byte_size: int
    mime_type: str
    raw_payload_sha256: str

    def to_row(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> RawDocumentBlob:
        return cls(
            doc_id=str(row["doc_id"]),
            accession=str(row["accession"]),
            document_path=str(row["document_path"]),
            byte_size=int(row["byte_size"]),
            mime_type=str(row["mime_type"]),
            raw_payload_sha256=str(row["raw_payload_sha256"]),
        )


@dataclass(frozen=True, slots=True)
class NormalizedDocument:
    """Normalized document representation record."""

    normalized_artifact_id: str
    source_doc_id: str
    byte_size: int
    normalized_payload: bytes
    payload_sha256: str
    mime_type: str
    representation: str
    processor_fingerprint: str
    schema_version: int
    processor_metadata: str

    def to_row(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class NormalizationFailure:
    """Audit record for a document normalization failure."""

    source_doc_id: str
    processor_fingerprint: str
    schema_version: int
    error_message: str
    attempted_at: str

    def to_row(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class FilingOccurrence:
    """Provenance link from one corporate CIK occurrence to a stored document blob."""

    occurrence_id: str
    source_cik: Cik
    accession: AccessionNumber
    document_path: str
    form: str
    filing_date: str
    report_date: str | None
    doc_id: str

    def to_row(self) -> dict[str, Any]:
        return {
            "occurrence_id": self.occurrence_id,
            "source_cik": self.source_cik.to_10digit(),
            "accession": str(self.accession),
            "document_path": self.document_path,
            "form": self.form,
            "filing_date": self.filing_date,
            "report_date": self.report_date,
            "doc_id": self.doc_id,
        }

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> FilingOccurrence:
        report_date = row.get("report_date")
        return cls(
            occurrence_id=str(row["occurrence_id"]),
            source_cik=Cik.from_raw(row["source_cik"]),
            accession=AccessionNumber(str(row["accession"])),
            document_path=str(row["document_path"]),
            form=str(row["form"]),
            filing_date=str(row["filing_date"]),
            report_date=None if report_date is None else str(report_date),
            doc_id=str(row["doc_id"]),
        )


__all__ = [
    "DocumentKind",
    "DocumentLocator",
    "FilingOccurrence",
    "NormalizationFailure",
    "NormalizedDocument",
    "RawDocumentBlob",
    "derive_document_locator_key",
    "derive_occurrence_id",
]
