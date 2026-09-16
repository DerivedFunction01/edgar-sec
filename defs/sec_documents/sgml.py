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


__all__ = [
    "SgmlSubDocument",
    "extract_sub_document",
    "find_sub_document",
    "resolve_target_sub_document",
    "unpack_sgml_submission",
]
