"""SGML multi-document envelope unpacker for SEC EDGAR submissions.

SEC EDGAR submissions (.txt / .sgml) can bundle multiple documents within
a single text file using SGML-style <DOCUMENT>...</DOCUMENT> wrapper tags.
This module extracts individual sub-documents and filters for target exhibits
(such as Exhibit 13) while discarding unnecessary documents, graphics, and
envelope metadata.
"""

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

# Bytes twins of the header regexes for the selective extractor: scanning the
# raw envelope avoids the full latin-1 str decode of ``unpack_sgml_submission``
# while matching exactly the same ASCII tag shapes.
_RE_DOCUMENT_B = re.compile(rb"(?is)<DOCUMENT>(.*?)</DOCUMENT>")
_RE_TAG_TYPE_B = re.compile(rb"(?im)^\s*<TYPE>\s*([^\r\n<]+)")
_RE_TAG_SEQUENCE_B = re.compile(rb"(?im)^\s*<SEQUENCE>\s*([^\r\n<]+)")
_RE_TAG_FILENAME_B = re.compile(rb"(?im)^\s*<FILENAME>\s*([^\r\n<]+)")
_RE_TAG_TEXT_B = re.compile(rb"(?is)<TEXT>(.*?)</TEXT>")


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


def unpack_sgml_submission(raw_bytes: bytes) -> list[SgmlSubDocument]:
    """Parse an SGML submission envelope and extract sub-documents.

    Each document is enclosed within `<DOCUMENT>` ... `</DOCUMENT>`.
    Tags `<TYPE>`, `<SEQUENCE>`, `<FILENAME>`, `<DESCRIPTION>`, and `<TEXT>`
    are parsed. Content inside `<TEXT>...</TEXT>` is extracted as the document's
    raw payload.
    """
    if not raw_bytes:
        return []

    # EDGAR submissions are either ASCII, UTF-8, Windows-1252, or Latin-1.
    # Latin-1 decodes all byte streams 1-to-1 without error.
    text = raw_bytes.decode("latin-1", errors="replace")

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
            # Fallback if closing </TEXT> tag is omitted in malformed envelopes
            inner_text = doc_block.strip()

        # Re-encode payload back to original bytes (Latin-1 preserves original bytes exactly)
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
    """Find a matching sub-document from unpacked SGML sub-documents.

    Matches by target document types (case-insensitive exact match) or
    substring patterns in filenames (case-insensitive, excluding graphics/binaries).
    """
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


def extract_sub_document(
    raw_sgml: bytes,
    target_types: Sequence[str] | None = None,
    filename_patterns: Sequence[str] | None = None,
) -> SgmlSubDocument | None:
    """Unpack an SGML submission envelope and extract a target sub-document.

    Generic across any form family and exhibit type (e.g., 10-K, 10-Q, 8-K, 6-K,
    EX-13, EX-99, EX-2.1, etc.).

    Parameters
    ----------
    raw_sgml : bytes
        Raw bytes of the SGML submission file (.txt or .sgml).
    target_types : Sequence[str], optional
        Target document types to match against `<TYPE>` tags (e.g. `["EX-13", "EX-99"]`).
    filename_patterns : Sequence[str], optional
        Substring patterns to match against `<FILENAME>` tags (e.g. `["ex13", "report"]`).
    """
    sub_docs = unpack_sgml_submission(raw_sgml)
    return find_sub_document(
        sub_docs,
        target_types=target_types,
        filename_patterns=filename_patterns,
    )


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


def resolve_target_sub_document(
    sub_docs: Sequence[SgmlSubDocument],
    *,
    target_types: Sequence[str] | None = None,
    primary_filename: str | None = None,
    fallback_to_sequence_one: bool = True,
) -> SgmlSubDocument | None:
    """Resolve a target filing document from unpacked SGML sub-documents.

    Generic across all SEC form families and exhibits without hardcoding form names:
    1. Matches caller-supplied ``target_types`` against ``<TYPE>`` (case-insensitive).
    2. Matches caller-supplied ``primary_filename`` against ``<FILENAME>`` (case-insensitive).
    3. Matches ``<SEQUENCE> 1`` (standard primary filing position in SEC submissions).
    4. First non-graphic text/HTML sub-document fallback.
    """
    if not sub_docs:
        return None

    # Tier 1: Match by Target Types
    if target_types:
        targets = {t.strip().upper() for t in target_types if t and t.strip()}
        for doc in sub_docs:
            if doc.doc_type in targets and not doc.filename.lower().endswith(
                _NON_TEXT_EXTENSIONS
            ):
                return doc

    # Tier 2: Match by Primary Filename
    if primary_filename:
        p_base = primary_filename.split("/")[-1].strip().upper()
        if p_base and not p_base.startswith("0001.") and not p_base.startswith("0000."):
            for doc in sub_docs:
                if doc.filename.strip().upper() == p_base:
                    return doc

    # Tier 3: Match by Primary Sequence (Sequence 1)
    if fallback_to_sequence_one:
        for doc in sub_docs:
            if (
                doc.sequence == 1
                and doc.doc_type not in ("GRAPHIC", "COVER", "XML")
                and not doc.filename.lower().endswith(_NON_TEXT_EXTENSIONS)
            ):
                return doc

    # Tier 4: First non-graphic text/HTML sub-document
    for doc in sub_docs:
        if doc.doc_type not in (
            "GRAPHIC",
            "XML",
            "ZIP",
        ) and not doc.filename.lower().endswith(_NON_TEXT_EXTENSIONS):
            return doc

    return None


def strip_pem_envelope(raw: bytes) -> bytes:
    """Remove a leading PEM (privacy-enhanced message) transport wrapper.

    SEC EDGAR occasionally delivers whole submission bundles wrapped in a
    cleartext PEM envelope: ``-----BEGIN PRIVACY-ENHANCED MESSAGE-----``, a
    short header block (``Proc-Type``, ``Originator-*``, ``MIC-Info``), a blank
    separator line, then the actual SGML submission, closed by
    ``-----END PRIVACY-ENHANCED MESSAGE-----``.

    Only the transport framing is removed: the begin/end delimiter lines and
    the RFC-1113 header block that precedes the first blank line. The enclosed
    SEC bytes are returned unchanged. Payloads without a well-formed leading
    envelope are returned unmodified.
    """
    if not raw:
        return raw
    start = raw.find(_PEM_BEGIN)
    if start == -1:
        return raw
    content_at = start + len(_PEM_BEGIN)
    end = raw.find(_PEM_END, content_at)
    if end == -1:
        return raw

    # The header block ends at the first blank line; the enclosed submission
    # starts after it. Fall back to the content immediately following the
    # begin marker when no separator exists.
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
    # Drop the leading newline of the body delimiter pair.
    if body.startswith((b"\n", b"\r")):
        body = body[1:]
    tail = raw[end + len(_PEM_END) :]
    return body.lstrip(b"\r\n") + tail


def has_sgml_documents(raw_bytes: bytes) -> bool:
    """True when the envelope contains at least one ``<DOCUMENT>`` block."""
    if not raw_bytes:
        return False
    return _RE_DOCUMENT_B.search(raw_bytes) is not None


def extract_target_sub_document(
    raw_bytes: bytes,
    *,
    target_types: Sequence[str] | None = None,
    primary_filename: str | None = None,
    fallback_to_sequence_one: bool = True,
) -> bytes | None:
    """Selectively extract the resolved target sub-document payload.

    Resolves the winner through :func:`resolve_target_sub_document` using the
    same tier semantics as ``unpack_sgml_submission`` output, but scans the
    raw bytes and materializes only the winning sub-document's payload
    instead of decoding the envelope and unpacking every sub-document.

    Returns ``None`` only when blocks exist yet none resolves; callers that
    treat block-less payloads as whole documents check
    :func:`has_sgml_documents` first.
    """
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
                # Equivalent to decoding latin-1, stripping \r\n, and
                # re-encoding: latin-1 decodes every byte losslessly.
                return text_match.group(1).strip(b"\r\n")
            return block.decode("latin-1").strip().encode("latin-1")
    return None  # pragma: no cover - winner always comes from refs


def _clean_b_field(match: re.Match[bytes] | None) -> str | None:
    if match is None:
        return None
    val = match.group(1).decode("latin-1").strip()
    return val if val else None


__all__ = [
    "SgmlSubDocument",
    "extract_sub_document",
    "extract_target_sub_document",
    "find_sub_document",
    "has_sgml_documents",
    "resolve_target_sub_document",
    "strip_pem_envelope",
    "unpack_sgml_submission",
]
