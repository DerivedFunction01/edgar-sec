"""Typed records for the Phase 2.5 schema contract."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True, slots=True)
class RawDocumentBlob:
    """One deduplicated compressed raw payload."""

    doc_id: str
    accession: str
    document_path: str
    byte_size: int
    mime_type: str
    raw_payload: bytes
    raw_payload_sha256: str

    def to_row(self) -> dict:
        return asdict(self)

    @classmethod
    def from_row(cls, row: dict) -> RawDocumentBlob:
        return cls(
            doc_id=str(row["doc_id"]),
            accession=str(row["accession"]),
            document_path=str(row["document_path"]),
            byte_size=int(row["byte_size"]),
            mime_type=str(row["mime_type"]),
            raw_payload=bytes(row["raw_payload"]),
            raw_payload_sha256=str(row["raw_payload_sha256"]),
        )


@dataclass(frozen=True, slots=True)
class NormalizedDocument:
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

    def to_row(self) -> dict:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class NormalizationFailure:
    source_doc_id: str
    processor_fingerprint: str
    schema_version: int
    error_message: str
    attempted_at: str

    def to_row(self) -> dict:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class FilingOccurrence:
    """Provenance link from one corporate occurrence to a stored blob."""

    occurrence_id: str
    source_cik: str
    accession: str
    document_path: str
    form: str
    filing_date: str
    report_date: str | None
    doc_id: str

    def to_row(self) -> dict:
        return asdict(self)

    @classmethod
    def from_row(cls, row: dict) -> FilingOccurrence:
        report_date = row["report_date"]
        return cls(
            occurrence_id=str(row["occurrence_id"]),
            source_cik=str(row["source_cik"]),
            accession=str(row["accession"]),
            document_path=str(row["document_path"]),
            form=str(row["form"]),
            filing_date=str(row["filing_date"]),
            report_date=None if report_date is None else str(report_date),
            doc_id=str(row["doc_id"]),
        )


@dataclass(frozen=True, slots=True)
class CommittedChunk:
    """Resumability audit row for one merged worker chunk."""

    chunk_id: str
    record_count: int
    worker_id: str
    committed_at: str
    processor_fingerprint: str
    normalized_schema_version: int

    def to_row(self) -> dict:
        return asdict(self)

    @classmethod
    def from_row(cls, row: dict) -> CommittedChunk:
        from .schemas import NORMALIZED_SCHEMA_VERSION

        return cls(
            chunk_id=str(row["chunk_id"]),
            record_count=int(row["record_count"]),
            worker_id=str(row["worker_id"]),
            committed_at=str(row["committed_at"]),
            processor_fingerprint=str(row.get("processor_fingerprint", "raw-only")),
            normalized_schema_version=int(
                row.get("normalized_schema_version", NORMALIZED_SCHEMA_VERSION)
            ),
        )


@dataclass(frozen=True, slots=True)
class AcquisitionFailure:
    """A document acquisition failure or missing payload record."""

    doc_id: str
    accession: str
    document_path: str
    status: str
    error_message: str | None
    attempted_at: str

    def to_row(self) -> dict:
        return asdict(self)

    @classmethod
    def from_row(cls, row: dict) -> AcquisitionFailure:
        err = row.get("error_message")
        return cls(
            doc_id=str(row["doc_id"]),
            accession=str(row["accession"]),
            document_path=str(row["document_path"]),
            status=str(row["status"]),
            error_message=None if err is None else str(err),
            attempted_at=str(row["attempted_at"]),
        )


@dataclass(frozen=True, slots=True)
class DocumentLocator:
    """One unique pre-capture locator from a Phase 02 target plan."""

    locator_key: str
    accession: str
    document_path: str
    archive_url: str
    form: str = ""


@dataclass(frozen=True, slots=True)
class FetchResult:
    """Outcome of one acquisition attempt for a locator."""

    locator: DocumentLocator
    payload: bytes | None
    status: str  # "ok" | "missing" | "failed"
    error: str | None = None


__all__ = [
    "AcquisitionFailure",
    "CommittedChunk",
    "DocumentLocator",
    "FetchResult",
    "FilingOccurrence",
    "NormalizationFailure",
    "NormalizedDocument",
    "RawDocumentBlob",
]
