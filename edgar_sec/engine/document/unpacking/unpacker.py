"""SGML multi-document envelope unpacker for SEC EDGAR submissions."""

from __future__ import annotations

import re
from collections.abc import Collection, Sequence
from dataclasses import dataclass

from edgar_sec.domain.document.acquisition import (
    SubmissionDocument,
    describe_submission_document,
)
from edgar_sec.domain.document.route import (
    DocumentRoute,
    content_route,
    is_markup_document_path,
)

_RE_DOCUMENT = re.compile(r"(?is)<DOCUMENT>(.*?)</DOCUMENT>")
_RE_TAG_TYPE = re.compile(r"(?im)^\s*<TYPE>\s*([^\r\n<]+)")
_RE_TAG_SEQUENCE = re.compile(r"(?im)^\s*<SEQUENCE>\s*([^\r\n<]+)")
_RE_TAG_FILENAME = re.compile(r"(?im)^\s*<FILENAME>\s*([^\r\n<]+)")
_RE_TAG_DESCRIPTION = re.compile(r"(?im)^\s*<DESCRIPTION>\s*([^\r\n<]+)")
_RE_TAG_TEXT = re.compile(r"(?is)<TEXT>(.*?)</TEXT>")

_PEM_BEGIN = b"-----BEGIN PRIVACY-ENHANCED MESSAGE-----"
_PEM_END = b"-----END PRIVACY-ENHANCED MESSAGE-----"

_RE_DOCUMENT_B = re.compile(rb"(?is)<DOCUMENT>(.*?)</DOCUMENT>")
_RE_TAG_TYPE_B = re.compile(rb"(?im)^\s*<TYPE>\s*([^\r\n<]+)")
_RE_TAG_SEQUENCE_B = re.compile(rb"(?im)^\s*<SEQUENCE>\s*([^\r\n<]+)")
_RE_TAG_FILENAME_B = re.compile(rb"(?im)^\s*<FILENAME>\s*([^\r\n<]+)")
_RE_TAG_DESCRIPTION_B = re.compile(rb"(?im)^\s*<DESCRIPTION>\s*([^\r\n<]+)")
_RE_TAG_TEXT_B = re.compile(rb"(?is)<TEXT>(.*?)</TEXT>")

# Delimiter counters for structural validation; a submission may not nest <DOCUMENT>
# blocks beneath one another.
_RE_DOC_OPEN_B = re.compile(rb"<DOCUMENT>")
_RE_DOC_CLOSE_B = re.compile(rb"</DOCUMENT>")

_NON_TEXT_EXTENSIONS = (
    ".jpg",
    ".jpeg",
    ".gif",
    ".png",
    ".pdf",
    ".zip",
    ".xlsx",
    ".xls",
    ".fil",
)


@dataclass(frozen=True, slots=True)
class SgmlSubDocument:
    """One extracted sub-document from an SGML submission envelope."""

    doc_type: str
    sequence: int | None
    filename: str
    description: str | None
    raw_payload: bytes
    is_html: bool


def _clean_field(match: re.Match[str] | None) -> str | None:
    if match is None:
        return None
    val = match.group(1).strip()
    return val if val else None


def _clean_b_field(match: re.Match[bytes] | None) -> str | None:
    if match is None:
        return None
    val = match.group(1).decode("latin-1").strip()
    return val if val else None


def strip_pem_envelope(raw: bytes) -> bytes:
    """Remove a leading PEM (privacy-enhanced message) transport wrapper."""
    if not raw:
        return raw
    start = raw.find(_PEM_BEGIN)
    if start == -1:
        return raw
    content_at = start + len(_PEM_BEGIN)
    end = raw.find(_PEM_END, content_at)
    if end == -1:
        return raw

    header_end = raw.find(b"\n\n", content_at)
    if header_end == -1 or header_end > end:
        header_end = raw.find(b"\r\n\r\n", content_at)
        if header_end == -1 or header_end > end:
            header_end = content_at - 1
    else:
        crlf = raw.find(b"\r\n\r\n", content_at)
        if crlf != -1 and crlf < header_end:
            header_end = crlf

    body = raw[header_end + 1 : end]
    if body.startswith((b"\n", b"\r")):
        body = body[1:]
    tail = raw[end + len(_PEM_END) :]
    return body.lstrip(b"\r\n") + tail


def has_sgml_documents(raw_bytes: bytes) -> bool:
    """True when the envelope contains at least one <DOCUMENT> block."""
    if not raw_bytes:
        return False
    return _RE_DOCUMENT_B.search(raw_bytes) is not None


def unpack_sgml_submission(raw_bytes: bytes | str) -> list[SgmlSubDocument]:
    """Parse an SGML submission envelope and extract all sub-documents."""
    if not raw_bytes:
        return []

    # EDGAR submissions are decoded losslessly with latin-1
    text = (
        raw_bytes
        if isinstance(raw_bytes, str)
        else raw_bytes.decode("latin-1", errors="replace")
    )

    sub_docs: list[SgmlSubDocument] = []
    for doc_match in _RE_DOCUMENT.finditer(text):
        doc_block = doc_match.group(1)

        doc_type_raw = _clean_field(_RE_TAG_TYPE.search(doc_block)) or ""
        doc_type = doc_type_raw.upper()

        seq_raw = _clean_field(_RE_TAG_SEQUENCE.search(doc_block))
        sequence: int | None = None
        if seq_raw:
            try:
                sequence = int(seq_raw)
            except ValueError:
                sequence = None

        filename = _clean_field(_RE_TAG_FILENAME.search(doc_block)) or ""
        description = _clean_field(_RE_TAG_DESCRIPTION.search(doc_block))

        text_match = _RE_TAG_TEXT.search(doc_block)
        if text_match:
            inner_text = text_match.group(1).strip("\r\n")
        else:
            inner_text = doc_block.strip()

        payload = inner_text.encode("latin-1")
        is_html = (
            is_markup_document_path(filename)
            or "<html" in inner_text[:1000].lower()
            or "<!doctype html" in inner_text[:1000].lower()
        )

        sub_docs.append(
            SgmlSubDocument(
                doc_type=doc_type,
                sequence=sequence,
                filename=filename,
                description=description,
                raw_payload=payload,
                is_html=is_html,
            )
        )

    return sub_docs


def find_sub_document(
    sub_docs: Sequence[SgmlSubDocument],
    target_types: Sequence[str] | None = None,
    filename_patterns: Sequence[str] | None = None,
) -> SgmlSubDocument | None:
    """Find a matching sub-document by target types or filename patterns."""
    if target_types:
        targets = {t.strip().upper() for t in target_types}
        for doc in sub_docs:
            if doc.doc_type in targets:
                return doc

    if filename_patterns:
        patterns = [p.strip().upper() for p in filename_patterns]
        for doc in sub_docs:
            fn_upper = doc.filename.upper()
            if any(p in fn_upper for p in patterns) and not fn_upper.endswith(
                (".JPG", ".JPEG", ".GIF", ".PNG", ".PDF", ".ZIP")
            ):
                return doc

    return None


def resolve_target_sub_document(
    sub_docs: Sequence[SgmlSubDocument],
    *,
    target_types: Sequence[str] | None = None,
    primary_filename: str | None = None,
    fallback_to_sequence_one: bool = True,
) -> SgmlSubDocument | None:
    """Resolve the primary or target document from unpacked sub-documents."""
    if not sub_docs:
        return None

    # Tiered resolution: target types, then primary filename, then primary sequence, then first text/HTML.
    # Tier 1: Match by Target Types
    if target_types:
        targets = {t.strip().upper() for t in target_types if t and t.strip()}
        for doc in sub_docs:
            if doc.doc_type in targets and not doc.filename.lower().endswith(
                _NON_TEXT_EXTENSIONS
            ):
                return doc

    if primary_filename:
        p_base = primary_filename.split("/")[-1].strip().upper()
        if p_base and not p_base.startswith("0001.") and not p_base.startswith("0000."):
            for doc in sub_docs:
                if doc.filename.strip().upper() == p_base:
                    return doc

    if fallback_to_sequence_one:
        for doc in sub_docs:
            if (
                doc.sequence == 1
                and doc.doc_type not in ("GRAPHIC", "COVER", "XML")
                and not doc.filename.lower().endswith(_NON_TEXT_EXTENSIONS)
            ):
                return doc

    for doc in sub_docs:
        if doc.doc_type not in (
            "GRAPHIC",
            "XML",
            "ZIP",
        ) and not doc.filename.lower().endswith(_NON_TEXT_EXTENSIONS):
            return doc

    return None


@dataclass(frozen=True, slots=True)
class SgmlSubDocumentSelection:
    """A chosen sub-document's payload, with every sub-document's headers.

    ``selected_index`` locates the body: a filename or sequence number may be absent or
    duplicated, so neither can identify it.
    """

    payload: bytes
    documents: tuple[SubmissionDocument, ...]
    selected_index: int


def extract_target_sub_document_selection(
    raw_bytes: bytes,
    *,
    target_types: Sequence[str] | None = None,
    primary_filename: str | None = None,
    fallback_to_sequence_one: bool = True,
) -> SgmlSubDocumentSelection | None:
    """Select one sub-document's payload and describe every sub-document in order.

    Resolution is ``resolve_target_sub_document``'s, unchanged; this adds the ordered
    header record and reports which position the payload came from.
    """
    if not raw_bytes:
        return None

    refs: list[tuple[SgmlSubDocument, int, int]] = []
    headers: list[SubmissionDocument] = []
    for match in _RE_DOCUMENT_B.finditer(raw_bytes):
        block = raw_bytes[match.start(1) : match.end(1)]
        doc_type_raw = _clean_b_field(_RE_TAG_TYPE_B.search(block)) or ""
        seq_raw = _clean_b_field(_RE_TAG_SEQUENCE_B.search(block))
        sequence: int | None = None
        if seq_raw:
            try:
                sequence = int(seq_raw)
            except ValueError:
                sequence = None
        filename = _clean_b_field(_RE_TAG_FILENAME_B.search(block)) or ""
        light = SgmlSubDocument(
            doc_type=doc_type_raw.upper(),
            sequence=sequence,
            filename=filename,
            description=None,
            raw_payload=b"",
            is_html=False,
        )
        refs.append((light, match.start(1), match.end(1)))
        headers.append(
            describe_submission_document(
                document_path=filename,
                # A slash in a sub-document's own filename never names an XSL
                # rendering directory, so the route ignores directories here.
                content_route=content_route(filename),
                sequence=sequence,
                doc_type=doc_type_raw.upper() or None,
                description=_clean_b_field(_RE_TAG_DESCRIPTION_B.search(block)),
            )
        )

    if not refs:
        return None

    winner = resolve_target_sub_document(
        [doc for doc, _, _ in refs],
        target_types=target_types,
        primary_filename=primary_filename,
        fallback_to_sequence_one=fallback_to_sequence_one,
    )
    if winner is None:
        return None
    for index, (doc, start, end) in enumerate(refs):
        if doc is not winner:
            continue
        block = raw_bytes[start:end]
        text_match = _RE_TAG_TEXT_B.search(block)
        if text_match is not None:
            payload = text_match.group(1).strip(b"\r\n")
        else:
            payload = block.decode("latin-1").strip().encode("latin-1")
        return SgmlSubDocumentSelection(
            payload=payload,
            documents=tuple(headers),
            selected_index=index,
        )
    return None


def extract_target_sub_document(
    raw_bytes: bytes,
    *,
    target_types: Sequence[str] | None = None,
    primary_filename: str | None = None,
    fallback_to_sequence_one: bool = True,
) -> bytes | None:
    """Selectively extract the resolved target sub-document payload."""
    selection = extract_target_sub_document_selection(
        raw_bytes,
        target_types=target_types,
        primary_filename=primary_filename,
        fallback_to_sequence_one=fallback_to_sequence_one,
    )
    return None if selection is None else selection.payload


@dataclass(frozen=True, slots=True)
class _ResolvedDocument:
    """One document header with its sliced body; internal to this module."""

    document_path: str | None
    content_route: DocumentRoute
    sequence: int | None
    doc_type: str | None
    description: str | None
    payload: bytes


@dataclass(frozen=True, slots=True)
class FilingResolutionScan:
    """Every document header in a bundle plus the only bodies the resolver retains.

    ``documents`` lists every header in envelope order; ``requested`` and ``primary``
    carry the two bodies the resolver keeps. ``scan_error`` records delimiter problems.
    """

    documents: tuple[SubmissionDocument, ...]
    requested: _ResolvedDocument | None
    primary: _ResolvedDocument | None
    requested_match_count: int
    primary_sequence_tie: bool
    primary_invalid_sequence: bool
    scan_error: str | None


def _check_document_delimiters(raw_bytes: bytes) -> str | None:
    """Return an error when ``<DOCUMENT>`` delimiters are unbalanced or nested."""
    if not raw_bytes:
        return None
    positions: list[tuple[int, int]] = []
    for m in _RE_DOC_OPEN_B.finditer(raw_bytes):
        positions.append((m.start(), 1))
    for m in _RE_DOC_CLOSE_B.finditer(raw_bytes):
        positions.append((m.start(), -1))
    positions.sort()
    depth = 0
    for _, delta in positions:
        depth += delta
        if depth < 0:
            return "unbalanced </DOCUMENT> delimiter"
        if depth > 1:
            return "nested <DOCUMENT> delimiter"
    if depth != 0:
        return "unbalanced <DOCUMENT> delimiter"
    return None


def _parse_document_headers(
    raw_bytes: bytes,
) -> list[tuple[int, int, SubmissionDocument]]:
    """Return (start, end, descriptor) for every document block in envelope order."""
    entries: list[tuple[int, int, SubmissionDocument]] = []
    for m in _RE_DOCUMENT_B.finditer(raw_bytes):
        block = raw_bytes[m.start(1) : m.end(1)]
        doc_type_raw = _clean_b_field(_RE_TAG_TYPE_B.search(block)) or ""
        doc_type = doc_type_raw.upper()
        seq_raw = _clean_b_field(_RE_TAG_SEQUENCE_B.search(block))
        sequence: int | None = None
        if seq_raw:
            try:
                sequence = int(seq_raw)
            except ValueError:
                sequence = None
        filename = _clean_b_field(_RE_TAG_FILENAME_B.search(block)) or ""
        description = _clean_b_field(_RE_TAG_DESCRIPTION_B.search(block))
        entries.append(
            (
                m.start(1),
                m.end(1),
                describe_submission_document(
                    document_path=filename,
                    content_route=content_route(filename),
                    sequence=sequence,
                    doc_type=doc_type or None,
                    description=description,
                ),
            )
        )
    return entries


def _slice_body(raw_bytes: bytes, block_start: int, block_end: int) -> bytes:
    """Extract the TEXT body of a document block, or the whole block if no TEXT."""
    block = raw_bytes[block_start:block_end]
    m = _RE_TAG_TEXT_B.search(block)
    if m is not None:
        return m.group(1).strip(b"\r\n")
    return block.decode("latin-1").strip().encode("latin-1")


def scan_filing_bundle(
    raw_bytes: bytes,
    requested_path: str,
    accepted_types: Collection[str],
) -> FilingResolutionScan:
    """Inspect every header in a bundle and slice only the retained bodies.

    ``requested_path`` matched by exact basename; the primary is the accepted
    header with the lowest valid ``<SEQUENCE>``. Only two bodies survive.
    """
    if not raw_bytes:
        return FilingResolutionScan(
            documents=(),
            requested=None,
            primary=None,
            requested_match_count=0,
            primary_sequence_tie=False,
            primary_invalid_sequence=False,
            scan_error=None,
        )

    # Structural validation happens first: an unbalanced or nested envelope is a
    # structural failure, before any header semantics.
    scan_error = _check_document_delimiters(raw_bytes)

    entries = _parse_document_headers(raw_bytes)
    headers = tuple(e[2] for e in entries)
    offsets = tuple((e[0], e[1]) for e in entries)

    # Requested match: case-insensitive exact basename.
    requested_base = requested_path.strip().lower()
    match_indices = [
        i
        for i, d in enumerate(headers)
        if (d.document_path or "").strip().lower() == requested_base
    ]
    requested_match_count = len(match_indices)

    # Primary: lowest valid positive sequence among accepted types.
    accepted: set[str] = {t.strip().upper() for t in accepted_types}
    matching: list[int] = [
        i
        for i, d in enumerate(headers)
        if d.doc_type and d.doc_type.upper() in accepted
    ]
    valid: list[tuple[int, int]] = [
        (i, headers[i].sequence)
        for i in matching
        if isinstance(headers[i].sequence, int) and headers[i].sequence > 0
    ]
    invalid = [
        i
        for i in matching
        if not (isinstance(headers[i].sequence, int) and headers[i].sequence > 0)
    ]

    primary_index: int | None = None
    primary_sequence_tie = False
    primary_invalid_sequence = bool(invalid)

    if valid:
        min_seq = min(seq for _, seq in valid)
        best = [i for i, seq in valid if seq == min_seq]
        if len(best) == 1:
            primary_index = best[0]
        else:
            primary_sequence_tie = True

    requested_doc = None
    primary_doc = None
    if requested_match_count == 1:
        idx = match_indices[0]
        start, end = offsets[idx]
        requested_doc = _ResolvedDocument(
            document_path=headers[idx].document_path,
            content_route=headers[idx].content_route,
            sequence=headers[idx].sequence,
            doc_type=headers[idx].doc_type,
            description=headers[idx].description,
            payload=_slice_body(raw_bytes, start, end),
        )
    if primary_index is not None:
        start, end = offsets[primary_index]
        primary_doc = _ResolvedDocument(
            document_path=headers[primary_index].document_path,
            content_route=headers[primary_index].content_route,
            sequence=headers[primary_index].sequence,
            doc_type=headers[primary_index].doc_type,
            description=headers[primary_index].description,
            payload=_slice_body(raw_bytes, start, end),
        )

    return FilingResolutionScan(
        documents=headers,
        requested=requested_doc,
        primary=primary_doc,
        requested_match_count=requested_match_count,
        primary_sequence_tie=primary_sequence_tie,
        primary_invalid_sequence=primary_invalid_sequence,
        scan_error=scan_error,
    )


__all__ = [
    "FilingResolutionScan",
    "SgmlSubDocument",
    "SgmlSubDocumentSelection",
    "extract_target_sub_document",
    "extract_target_sub_document_selection",
    "find_sub_document",
    "has_sgml_documents",
    "resolve_target_sub_document",
    "strip_pem_envelope",
    "unpack_sgml_submission",
]
