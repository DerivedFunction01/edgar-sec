"""Pure HTML transformation: SEC ``-index.html`` to typed inventory outcomes.

Records live in `domain.document_inventory.models`; this module owns only the
transformation and its parser-implementation fingerprint.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from urllib.parse import SplitResult, parse_qs, urlsplit

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
from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.domain.sec_urls import validate_archive_url
from edgar_sec.engine.document.html.tree import FastHtmlNode, parse_html
from edgar_sec.foundation.hashing import sha256_bytes

__all__ = ["PARSER_FINGERPRINT", "parse_html_index"]

PARSER_FINGERPRINT = "index-page-v1"

_DIAGNOSTIC_LIMIT = 32
_DETAIL_LIMIT = 256
_HEADER_FIELDS = {
    "sequence": {"seq", "sequence", "sequence number"},
    "description": {"description"},
    "document": {"document"},
    "type": {"type"},
    "size": {"size"},
}
_TABLE_KINDS = {
    "document format files": "document_format",
    "data files": "data_file",
}


def parse_html_index(page: IndexPageInput) -> IndexParseOutcome:
    """Parse recognized document tables without network or artifact access."""
    digest = sha256_bytes(page.response_bytes)
    diagnostics = _DiagnosticCollector()
    try:
        source = page.response_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        return IndexParseFailure(
            page.accession,
            page.source_url,
            digest,
            ParserDiagnostic("unsupported_encoding", None, str(exc)[:_DETAIL_LIMIT]),
        )

    tree = parse_html(source)
    recognized: list[tuple[str, FastHtmlNode]] = []
    for table in tree.find_all("table"):
        kind = _table_kind(table)
        if kind is not None:
            recognized.append((kind, table))
        elif _looks_like_index_table(table):
            diagnostics.add(
                "unknown_table", None, "table has index-file columns but no known label"
            )
    if not recognized:
        return UnrecognizedIndexPage(
            page.accession, page.source_url, digest, diagnostics.freeze()
        )

    entries: list[InventoryEntry] = []
    bundle_url: str | None = None
    bundle_size: int | None = None
    next_ordinal = {kind: 0 for kind in _TABLE_KINDS.values()}
    seen_sequences: dict[str, set[int]] = {
        kind: set() for kind in _TABLE_KINDS.values()
    }
    last_sequences: dict[str, int | None] = {
        kind: None for kind in _TABLE_KINDS.values()
    }
    seen_filenames: set[str] = set()

    for kind, table in recognized:
        rows = table.find_all("tr")
        header_idx, columns = _find_header(rows)
        if header_idx is None:
            return IndexParseFailure(
                page.accession,
                page.source_url,
                digest,
                ParserDiagnostic(
                    "missing_column", None, f"{kind} table has no header row"
                ),
            )
        for name in _HEADER_FIELDS:
            if name not in columns:
                diagnostics.add("missing_column", None, f"{kind} table missing {name}")

        for row_index, row in enumerate(rows):
            if row_index == header_idx:
                continue
            cells = _direct_cells(row)
            if not cells or any(cell.tag == "th" for cell in cells):
                continue
            row_ordinal = next_ordinal[kind]
            next_ordinal[kind] += 1
            row_key = (kind, row_ordinal)
            values = {
                name: _cell_text(cells, columns.get(name)) for name in _HEADER_FIELDS
            }
            sequence = _parse_nonnegative(values["sequence"])
            byte_size = _parse_nonnegative(values["size"])

            document_cell = _cell(cells, columns.get("document"))
            anchor = document_cell.find("a") if document_cell is not None else None
            href = None
            if anchor is not None and "href" in anchor.raw_node.attrs:
                href = anchor.raw_node.attrs.get("href") or ""
            filename = _cell_text((anchor,), 0) if anchor is not None else None
            filename = filename or None
            description = values["description"] or None
            archive_url = None
            if href is not None:
                archive_url = _same_accession_archive_url(
                    page.source_url, href, page.accession
                )
                if archive_url is None:
                    diagnostics.add("unsafe_href", row_key, href)

            if _is_bundle_row(description, filename, page.accession):
                if bundle_url is not None:
                    diagnostics.add(
                        "duplicate_filename", row_key, "duplicate bundle row"
                    )
                elif archive_url is not None:
                    bundle_url = archive_url
                    bundle_size = byte_size
                elif byte_size is not None:
                    bundle_size = byte_size
                if byte_size is None:
                    diagnostics.add(
                        "invalid_size", row_key, values["size"] or "size is absent"
                    )
                continue

            if sequence is None:
                diagnostics.add(
                    "missing_sequence"
                    if not values["sequence"]
                    else "invalid_sequence",
                    row_key,
                    values["sequence"] or "sequence is absent",
                )
            else:
                if sequence in seen_sequences[kind]:
                    diagnostics.add("duplicate_sequence", row_key, str(sequence))
                if last_sequences[kind] is not None and sequence < last_sequences[kind]:
                    diagnostics.add("out_of_order_sequence", row_key, str(sequence))
                seen_sequences[kind].add(sequence)
                last_sequences[kind] = sequence
            if byte_size is None:
                diagnostics.add(
                    "invalid_size", row_key, values["size"] or "size is absent"
                )

            if filename:
                folded_filename = filename.casefold()
                if folded_filename in seen_filenames:
                    diagnostics.add("duplicate_filename", row_key, filename)
                seen_filenames.add(folded_filename)

            entries.append(
                InventoryEntry(
                    entry_id=inventory_entry_id(
                        page.accession, kind, row_ordinal, digest
                    ),
                    accession=page.accession,
                    table_kind=kind,
                    row_ordinal=row_ordinal,
                    sequence=sequence,
                    document_type=values["type"] or None,
                    document_label=values["document"] or None,
                    description=description,
                    filename=filename,
                    href=href,
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


class _DiagnosticCollector:
    __slots__ = ("items", "suppressed_count")

    def __init__(self) -> None:
        self.items: list[ParserDiagnostic] = []
        self.suppressed_count = 0

    def add(
        self,
        code: Literal[
            "unknown_table",
            "missing_column",
            "missing_sequence",
            "invalid_sequence",
            "duplicate_sequence",
            "out_of_order_sequence",
            "duplicate_filename",
            "invalid_size",
            "unsafe_href",
            "malformed_html",
            "unsupported_encoding",
        ],
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


def _normal(text: str) -> str:
    return " ".join(text.split()).casefold()


def _table_kind(table: FastHtmlNode) -> str | None:
    candidates = [table.get("summary", "") or ""]
    previous = table.find_previous_sibling()
    if previous is not None:
        candidates.append(previous.text())
    for candidate in candidates:
        normalized = _normal(candidate)
        for label, kind in _TABLE_KINDS.items():
            if normalized == label:
                return kind
    return None


def _direct_cells(row: FastHtmlNode) -> tuple[FastHtmlNode, ...]:
    cells = []
    child = row.raw_node.child
    while child is not None:
        if child.tag in {"th", "td"}:
            cells.append(FastHtmlNode(child))
        child = child.next
    return tuple(cells)


def _find_header(
    rows: list[FastHtmlNode],
) -> tuple[int | None, dict[str, int]]:
    for row_index, row in enumerate(rows):
        cells = _direct_cells(row)
        labels = [_normal(cell.text()) for cell in cells]
        header_labels = {
            alias for aliases in _HEADER_FIELDS.values() for alias in aliases
        }
        header_matches = sum(label in header_labels for label in labels)
        if not any(cell.tag == "th" for cell in cells) and header_matches < 2:
            continue
        columns: dict[str, int] = {}
        for index, label in enumerate(labels):
            for field, aliases in _HEADER_FIELDS.items():
                if label in aliases and field not in columns:
                    columns[field] = index
        return row_index, columns
    return None, {}


def _looks_like_index_table(table: FastHtmlNode) -> bool:
    rows = table.find_all("tr")
    _header_index, columns = _find_header(rows)
    return len(columns) >= 2


def _cell(cells: tuple[FastHtmlNode, ...], index: int | None) -> FastHtmlNode | None:
    if index is None or index >= len(cells):
        return None
    return cells[index]


def _cell_text(
    cells: tuple[FastHtmlNode, ...] | list[FastHtmlNode], index: int | None
) -> str:
    cell = _cell(tuple(cells), index)
    return " ".join(cell.text().split()) if cell is not None else ""


def _parse_nonnegative(value: str) -> int | None:
    text = value.strip()
    if not text:
        return None
    groups = text.split(",")
    if not groups[0].isdigit() or any(
        len(group) != 3 or not group.isdigit() for group in groups[1:]
    ):
        return None
    try:
        result = int("".join(groups))
    except ValueError:
        return None
    return result if result >= 0 else None


def _is_bundle_row(
    description: str | None,
    filename: str | None,
    accession: AccessionNumber,
) -> bool:
    if description and "complete submission text file" in _normal(description):
        return True
    return filename is not None and _normal(filename) == _normal(f"{accession}.txt")


def _same_accession_archive_url(
    source_url: str, href: str, accession: AccessionNumber
) -> str | None:
    if not href.strip():
        return None
    try:
        resolved = _resolve_href_without_normalizing(source_url, href.strip())
        target = urlsplit(resolved)
        source = urlsplit(source_url)
        source_archive = validate_archive_url(source_url, accession)
    except ValueError:
        return None
    if not _same_origin(source, target):
        return None
    if target.path == "/ix":
        document_paths = parse_qs(target.query, keep_blank_values=True).get("doc", [])
        if len(document_paths) != 1:
            return None
        try:
            resolved = _resolve_href_without_normalizing(
                f"{source.scheme}://{source.netloc}/", document_paths[0]
            )
            target = urlsplit(resolved)
        except ValueError:
            return None
    if not _same_origin(source, target):
        return None
    try:
        validate_archive_url(
            resolved,
            accession,
            expected_archive_cik=source_archive.archive_cik,
        )
    except ValueError:
        return None
    return resolved


def _same_origin(source: SplitResult, target: SplitResult) -> bool:
    return (
        target.scheme.casefold() == source.scheme.casefold()
        and target.netloc.casefold() == source.netloc.casefold()
    )


def _resolve_href_without_normalizing(source_url: str, href: str) -> str:
    source = urlsplit(source_url)
    reference = urlsplit(href)
    if reference.scheme:
        return href
    if reference.netloc:
        return f"{source.scheme}:{href}"
    origin = f"{source.scheme}://{source.netloc}"
    if reference.path.startswith("/"):
        path = reference.path
    else:
        directory = source.path.rsplit("/", 1)[0]
        path = f"{directory}/{reference.path}"
    resolved = origin + path
    if "?" in href:
        resolved += f"?{reference.query}"
    if "#" in href:
        resolved += f"#{reference.fragment}"
    return resolved
