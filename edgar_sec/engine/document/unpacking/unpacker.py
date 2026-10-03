"""SGML multi-document envelope unpacker for SEC EDGAR submissions."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

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
_RE_TAG_TEXT_B = re.compile(rb"(?is)<TEXT>(.*?)</TEXT>")

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
        lowered_filename = filename.lower()
        is_html = (
            lowered_filename.endswith((".htm", ".html", ".xhtml"))
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


def extract_target_sub_document(
    raw_bytes: bytes,
    *,
    target_types: Sequence[str] | None = None,
    primary_filename: str | None = None,
    fallback_to_sequence_one: bool = True,
) -> bytes | None:
    """Selectively extract the resolved target sub-document payload."""
    if not raw_bytes:
        return None

    refs: list[tuple[SgmlSubDocument, int, int]] = []
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
    for doc, start, end in refs:
        if doc is winner:
            block = raw_bytes[start:end]
            text_match = _RE_TAG_TEXT_B.search(block)
            if text_match is not None:
                return text_match.group(1).strip(b"\r\n")
            return block.decode("latin-1").strip().encode("latin-1")
    return None


__all__ = [
    "SgmlSubDocument",
    "extract_target_sub_document",
    "find_sub_document",
    "has_sgml_documents",
    "resolve_target_sub_document",
    "strip_pem_envelope",
    "unpack_sgml_submission",
]
