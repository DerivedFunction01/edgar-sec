"""Pure JSON transformation: SEC directory ``index.json`` to inventory outcomes.

Records live in `domain.document_inventory.models`; this module owns only the
transformation and its parser-implementation fingerprint.
"""

from __future__ import annotations

import json
from typing import Literal

from edgar_sec.domain.document_inventory.models import (
    IndexPageInput,
    IndexParseFailure,
    IndexParseOutcome,
    InventoryEntry,
    ParserDiagnostic,
    ParserDiagnostics,
    ParsedIndexPage,
    UnrecognizedIndexPage,
    inventory_entry_id,
)
from edgar_sec.domain.sec_urls import archives_url, parse_archive_url
from edgar_sec.foundation.hashing import sha256_bytes

__all__ = ["PARSER_FINGERPRINT", "parse_json_index"]

PARSER_FINGERPRINT = "index-json-v1"

_DIAGNOSTIC_LIMIT = 32
_DETAIL_LIMIT = 256
_TABLE_KIND = "document_format"
_INDEX_ARTIFACT_SUFFIXES = ("-index.html", "-index-headers.html", "-index-headers.txt")


def parse_json_index(page: IndexPageInput) -> IndexParseOutcome:
    """Parse a directory ``index.json`` payload without network access."""
    digest = sha256_bytes(page.response_bytes)
    try:
        source = page.response_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        return IndexParseFailure(
            page.accession,
            page.source_url,
            digest,
            ParserDiagnostic("unsupported_encoding", None, str(exc)[:_DETAIL_LIMIT]),
        )
    try:
        payload = json.loads(source)
    except json.JSONDecodeError as exc:
        return IndexParseFailure(
            page.accession,
            page.source_url,
            digest,
            ParserDiagnostic("malformed_json", None, str(exc)[:_DETAIL_LIMIT]),
        )
    items = _directory_items(payload)
    if items is None:
        return UnrecognizedIndexPage(
            page.accession,
            page.source_url,
            digest,
            ParserDiagnostics(
                (
                    ParserDiagnostic(
                        "unknown_table", None, "payload has no directory item list"
                    ),
                ),
                0,
            ),
        )

    diagnostics = _DiagnosticCollector()
    parts = parse_archive_url(page.source_url)
    entries: list[InventoryEntry] = []
    bundle_url: str | None = None
    bundle_size: int | None = None
    seen_filenames: set[str] = set()

    for item in items:
        name = item["name"].strip()
        if name == "index.json" or name.endswith(_INDEX_ARTIFACT_SUFFIXES):
            continue
        byte_size = _parse_size(item.get("size"))
        archive_url = (
            archives_url(parts.archive_cik, page.accession.normalized, name)
            if parts is not None
            else None
        )
        if name == f"{page.accession}.txt":
            bundle_url = archive_url
            bundle_size = byte_size
            if byte_size is None:
                diagnostics.add("invalid_size", None, "bundle size is absent")
            continue
        row_ordinal = len(entries)
        row_key = (_TABLE_KIND, row_ordinal)
        if byte_size is None:
            diagnostics.add("invalid_size", row_key, "size is absent or invalid")
        folded = name.casefold()
        if folded in seen_filenames:
            diagnostics.add("duplicate_filename", row_key, name)
        seen_filenames.add(folded)
        entries.append(
            InventoryEntry(
                entry_id=inventory_entry_id(
                    page.accession, _TABLE_KIND, row_ordinal, digest
                ),
                accession=page.accession,
                table_kind=_TABLE_KIND,
                row_ordinal=row_ordinal,
                sequence=None,
                document_type=None,
                document_label=None,
                description=None,
                filename=name,
                href=name,
                archive_url=archive_url,
                byte_size=byte_size,
            )
        )

    return ParsedIndexPage(
        accession=page.accession,
        source_url=page.source_url,
        page_sha256=digest,
        entries=tuple(entries),
        bundle_url=bundle_url,
        bundle_size=bundle_size,
        xbrl_candidate_url=None,
        diagnostics=diagnostics.freeze(),
    )


def _directory_items(payload: object) -> list[dict] | None:
    if not isinstance(payload, dict):
        return None
    directory = payload.get("directory")
    if not isinstance(directory, dict):
        return None
    items = directory.get("item")
    if not isinstance(items, list):
        return None
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            return None
        if not item["name"].strip():
            return None
    return items


def _parse_size(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


class _DiagnosticCollector:
    __slots__ = ("items", "suppressed_count")

    def __init__(self) -> None:
        self.items: list[ParserDiagnostic] = []
        self.suppressed_count = 0

    def add(
        self,
        code: Literal["duplicate_filename", "invalid_size"],
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
