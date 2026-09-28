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


def derive_document_locator_key(accession: str, document_path: str) -> str:
    """Generate deterministic content-addressed key for an accession + document path pair."""
    return sha256_text(f"{accession.strip()}:{document_path.strip()}")


def derive_occurrence_id(source_cik: str, document_locator_key: str) -> str:
    """Generate deterministic occurrence identifier linking a CIK to a document locator."""
    return sha256_text(f"{source_cik.strip()}:{document_locator_key.strip()}")


@dataclass(frozen=True, slots=True)
class DocumentLocator:
    """Content-addressed reference to a filing document."""

    accession: AccessionNumber
    document_path: str
    document_locator_key: str

    @classmethod
    def from_parts(
        cls, accession: AccessionNumber | str, document_path: str
    ) -> DocumentLocator:
        acc = (
            accession
            if isinstance(accession, AccessionNumber)
            else AccessionNumber(accession)
        )
        path = document_path.strip()
        key = derive_document_locator_key(str(acc), path)
        return cls(accession=acc, document_path=path, document_locator_key=key)


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
