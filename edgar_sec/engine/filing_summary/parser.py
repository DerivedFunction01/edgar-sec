"""Pure transformation: FilingSummary XML or XBRL package to inventory outcomes.

Records live in `domain.document_inventory.models`; this module owns only the
transformation and its enumerator-implementation fingerprint.
"""

from __future__ import annotations

import io
import xml.etree.ElementTree as ET
import zipfile
from typing import Literal

from edgar_sec.domain.document_inventory.models import (
    EnumeratedDocuments,
    EnumerationFailure,
    EnumerationInput,
    EnumerationOutcome,
    InventoryEntry,
    ParserDiagnostic,
    ParserDiagnostics,
    UnrecognizedEnumeration,
    inventory_entry_id,
)
from edgar_sec.domain.sec_urls import archives_url, full_submission_url_for
from edgar_sec.foundation.hashing import sha256_bytes

__all__ = ["ENUMERATOR_FINGERPRINT", "parse_filing_summary", "parse_xbrl_package"]

ENUMERATOR_FINGERPRINT = "filing-summary-v1"

_DIAGNOSTIC_LIMIT = 32
_DETAIL_LIMIT = 256
_LINKBASE_TYPES = (
    ("_cal.xml", "EX-101.CAL", "XBRL TAXONOMY EXTENSION CALCULATION LINKBASE"),
    ("_def.xml", "EX-101.DEF", "XBRL TAXONOMY EXTENSION DEFINITION LINKBASE"),
    ("_lab.xml", "EX-101.LAB", "XBRL TAXONOMY EXTENSION LABEL LINKBASE"),
    ("_pre.xml", "EX-101.PRE", "XBRL TAXONOMY EXTENSION PRESENTATION LINKBASE"),
)
_SCHEMA_TYPE = ("EX-101.SCH", "XBRL TAXONOMY EXTENSION SCHEMA")
_INSTANCE_TYPE = ("EX-101.INS", "XBRL INSTANCE DOCUMENT")
_EXTRACTED_TYPE = ("XML", "EXTRACTED XBRL INSTANCE DOCUMENT")


def parse_filing_summary(document: EnumerationInput) -> EnumerationOutcome:
    """Enumerate one FilingSummary document without network or artifact access."""
    digest = sha256_bytes(document.response_bytes)
    diagnostics = _DiagnosticCollector()
    try:
        root = ET.fromstring(document.response_bytes)
    except ET.ParseError as exc:
        return EnumerationFailure(
            document.accession,
            document.source_url,
            "summary",
            digest,
            ParserDiagnostic("malformed_xml", None, str(exc)[:_DETAIL_LIMIT]),
        )
    sections = _summary_sections(root)
    if sections is None:
        return UnrecognizedEnumeration(
            document.accession,
            document.source_url,
            "summary",
            digest,
            diagnostics.freeze(),
        )
    members = [(name, None) for name in sections]
    return _synthesize(document, members, digest, diagnostics, vehicle="summary")


def parse_xbrl_package(document: EnumerationInput) -> EnumerationOutcome:
    """Enumerate one XBRL package from its zip directory, with member sizes."""
    digest = sha256_bytes(document.response_bytes)
    diagnostics = _DiagnosticCollector()
    try:
        with zipfile.ZipFile(io.BytesIO(document.response_bytes)) as archive:
            members = [
                (info.filename, info.file_size)
                for info in archive.infolist()
                if not info.is_dir()
            ]
    except zipfile.BadZipFile as exc:
        return EnumerationFailure(
            document.accession,
            document.source_url,
            "package",
            digest,
            ParserDiagnostic("malformed_package", None, str(exc)[:_DETAIL_LIMIT]),
        )
    return _synthesize(document, members, digest, diagnostics, vehicle="package")


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _summary_sections(root: ET.Element) -> list[str] | None:
    """InputFiles names followed by SupplementalFiles names; None if no InputFiles."""
    inputs: list[str] | None = None
    supplemental: list[str] = []
    for element in root.iter():
        tag = _local_name(element.tag)
        if tag not in {"InputFiles", "SupplementalFiles"}:
            continue
        names = []
        for child in element:
            if _local_name(child.tag) != "File":
                continue
            name = (child.text or "").strip() or (child.get("original") or "").strip()
            if name:
                names.append(name)
        if tag == "InputFiles":
            inputs = names
        else:
            supplemental = names
    if inputs is None:
        return None
    return inputs + supplemental


def _classify(name: str) -> tuple[str, str | None, str | None]:
    """Map one member name to (table_kind, document_type, description)."""
    lowered = name.lower()
    for suffix, document_type, description in _LINKBASE_TYPES:
        if lowered.endswith(suffix):
            return "data_file", document_type, description
    if lowered.endswith(".xsd"):
        return "data_file", _SCHEMA_TYPE[0], _SCHEMA_TYPE[1]
    if lowered.endswith(".xml"):
        return "data_file", _INSTANCE_TYPE[0], _INSTANCE_TYPE[1]
    return "document_format", None, None


def _synthesize(
    document: EnumerationInput,
    members: list[tuple[str, int | None]],
    digest: str,
    diagnostics: "_DiagnosticCollector",
    *,
    vehicle: Literal["summary", "package"],
) -> EnumeratedDocuments:
    format_rows: list[tuple[str, int | None]] = []
    data_rows: list[tuple[str, str, str, int | None]] = []
    seen: set[str] = {document.primary_document.casefold()}
    for name, size in members:
        folded = name.casefold()
        if folded in seen:
            if name != document.primary_document:
                diagnostics.add("duplicate_filename", None, name)
            continue
        seen.add(folded)
        table_kind, document_type, description = _classify(name)
        if table_kind == "data_file":
            assert document_type is not None and description is not None
            data_rows.append((name, document_type, description, size))
        else:
            format_rows.append((name, size))

    entries: list[InventoryEntry] = []
    primary_size = next(
        (size for name, size in members if name == document.primary_document), None
    )
    entries.append(
        _entry(
            document,
            "document_format",
            0,
            digest,
            document_type=document.form,
            description=None,
            filename=document.primary_document,
            byte_size=primary_size,
        )
    )
    for ordinal, (name, size) in enumerate(format_rows, start=1):
        entries.append(
            _entry(
                document,
                "document_format",
                ordinal,
                digest,
                document_type=None,
                description=None,
                filename=name,
                byte_size=size,
            )
        )
    for ordinal, (name, document_type, description, size) in enumerate(data_rows):
        entries.append(
            _entry(
                document,
                "data_file",
                ordinal,
                digest,
                document_type=document_type,
                description=description,
                filename=name,
                byte_size=size,
            )
        )
    if document.is_inline_xbrl:
        stem = document.primary_document.rsplit(".", 1)[0]
        entries.append(
            _entry(
                document,
                "data_file",
                len(data_rows),
                digest,
                document_type=_EXTRACTED_TYPE[0],
                description=_EXTRACTED_TYPE[1],
                filename=f"{stem}_htm.xml",
                byte_size=None,
            )
        )
    bundle_url = None
    if document.archive_cik.isdigit():
        bundle_url = full_submission_url_for(document.archive_cik, document.accession)
    return EnumeratedDocuments(
        accession=document.accession,
        source_url=document.source_url,
        vehicle=vehicle,
        page_sha256=digest,
        entries=tuple(entries),
        bundle_url=bundle_url,
        diagnostics=diagnostics.freeze(),
    )


def _entry(
    document: EnumerationInput,
    table_kind: Literal["document_format", "data_file"],
    row_ordinal: int,
    digest: str,
    *,
    document_type: str | None,
    description: str | None,
    filename: str,
    byte_size: int | None,
) -> InventoryEntry:
    return InventoryEntry(
        entry_id=inventory_entry_id(
            document.accession, table_kind, row_ordinal, digest
        ),
        accession=document.accession,
        table_kind=table_kind,
        row_ordinal=row_ordinal,
        sequence=None,
        document_type=document_type,
        document_label=filename,
        description=description,
        filename=filename,
        href=filename,
        archive_url=_archive_url(document, filename),
        byte_size=byte_size,
    )


def _archive_url(document: EnumerationInput, filename: str) -> str | None:
    if not document.archive_cik.isdigit():
        return None
    return archives_url(document.archive_cik, document.accession, filename)


class _DiagnosticCollector:
    __slots__ = ("items", "suppressed_count")

    def __init__(self) -> None:
        self.items: list[ParserDiagnostic] = []
        self.suppressed_count = 0

    def add(
        self,
        code: Literal["duplicate_filename"],
        row_key: tuple[Literal["document_format", "data_file"], int] | None,
        detail: str,
    ) -> None:
        if len(self.items) == _DIAGNOSTIC_LIMIT:
            self.suppressed_count += 1
            return
        self.items.append(
            ParserDiagnostic(code, row_key, " ".join(detail.split())[:_DETAIL_LIMIT])
        )

    def freeze(self) -> ParserDiagnostics:
        return ParserDiagnostics(tuple(self.items), self.suppressed_count)
