"""Path-facts classifier for document acquisition and storage routing.

Provides DocumentPathFacts: a shared classifier describing the locator.
Each pipeline interprets these facts through its own policy.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath

#: Flat suffixes carrying markup. Anything with a slash is HTML regardless of this.
MARKUP_SUFFIXES = frozenset({".htm", ".html", ".xhtml"})

#: Flat suffixes carrying text.
TEXT_SUFFIXES = frozenset({".txt"})

#: Flat suffixes carrying an XML-native filing's own markup.
XML_SUFFIXES = frozenset({".xml", ".xsd"})

#: Flat suffixes that are binary regardless of what the document means.
BINARY_SUFFIXES = frozenset({".pdf", ".gif", ".jpg"})

#: Flat suffixes that are opaque (raw-only) for acquisition.
OPAQUE_SUFFIXES = frozenset({".fil", ".zip", ".eis"})

PLACEHOLDER_PRIMARY_FILENAMES = frozenset(
    {"0001.txt", "0001.htm", "0000.txt", "0000.htm"}
)

#: Extension to MIME, kept stable so a document described by this pipeline and one
#: described earlier name the same type for the same path.
MIME_BY_SUFFIX = {
    ".gif": "image/gif",
    ".htm": "text/html",
    ".html": "text/html",
    ".jpg": "image/jpeg",
    ".pdf": "application/pdf",
    ".txt": "text/plain",
    ".xhtml": "text/html",
    ".xml": "text/xml",
    ".xsd": "text/xml",
}

DEFAULT_MIME = "application/octet-stream"

#: Flat suffix of an EDGAR paper submission. The served payload is a fixed SGML
#: stub pointing at an off-archive Document Control Number, never filing prose.
PAPER_SUFFIX = ".paper"


class DocumentSuffixClass(StrEnum):
    """Classification of a document's file suffix."""

    MARKUP = "markup"
    TEXT = "text"
    XML = "xml"
    PDF = "pdf"
    IMAGE = "image"
    PAPER = "paper"
    OPAQUE = "opaque"
    UNKNOWN = "unknown"


class DocumentPathShape(StrEnum):
    """Classification of a document's path shape."""

    FLAT = "flat"
    NESTED = "nested"


def _normalized_suffix(document_path: str) -> str:
    """Return the case-folded suffix of a path under EDGAR's separator spelling."""
    return PurePosixPath(document_path.strip().replace("\\", "/")).suffix.casefold()


def _classify_suffix(suffix: str) -> DocumentSuffixClass:
    """Classify an already-extracted suffix, with no directory consulted."""
    if suffix in MARKUP_SUFFIXES:
        return DocumentSuffixClass.MARKUP
    if suffix in TEXT_SUFFIXES:
        return DocumentSuffixClass.TEXT
    if suffix in XML_SUFFIXES:
        return DocumentSuffixClass.XML
    if suffix == PAPER_SUFFIX:
        return DocumentSuffixClass.PAPER
    if suffix in BINARY_SUFFIXES:
        if suffix == ".pdf":
            return DocumentSuffixClass.PDF
        return DocumentSuffixClass.IMAGE
    if suffix in OPAQUE_SUFFIXES:
        return DocumentSuffixClass.OPAQUE
    return DocumentSuffixClass.UNKNOWN


@dataclass(frozen=True, slots=True)
class DocumentPathFacts:
    """Independent path facts describing a document locator.

    path_context, path_shape, suffix, suffix_class.
    """

    path_context: str
    path_shape: DocumentPathShape
    suffix: str
    suffix_class: DocumentSuffixClass

    @classmethod
    def from_archive_path(cls, path: str) -> DocumentPathFacts:
        """Create path facts from an archive URL path.

        This constructor treats the path as an archive URL with potential directory
        semantics. Nested paths are flagged accordingly.
        """
        normalized = path.strip().replace("\\", "/")
        if not normalized:
            return cls(
                path_context="",
                path_shape=DocumentPathShape.FLAT,
                suffix="",
                suffix_class=DocumentSuffixClass.UNKNOWN,
            )
        suffix = _normalized_suffix(normalized)
        if "/" in normalized:
            return cls(
                path_context=normalized,
                path_shape=DocumentPathShape.NESTED,
                suffix=suffix,
                suffix_class=_classify_suffix(suffix),
            )
        return cls(
            path_context=normalized,
            path_shape=DocumentPathShape.FLAT,
            suffix=suffix,
            suffix_class=_classify_suffix(suffix),
        )

    @classmethod
    def from_sgml_filename(cls, filename: str) -> DocumentPathFacts:
        """Create path facts from an SGML filename.

        This constructor treats the input as an SGML <FILENAME> header value.
        Directory semantics are ignored; all inputs are treated as flat.
        """
        normalized = filename.strip().replace("\\", "/")
        if not normalized:
            return cls(
                path_context="",
                path_shape=DocumentPathShape.FLAT,
                suffix="",
                suffix_class=DocumentSuffixClass.UNKNOWN,
            )
        suffix = _normalized_suffix(normalized)
        return cls(
            path_context=normalized,
            path_shape=DocumentPathShape.FLAT,
            suffix=suffix,
            suffix_class=_classify_suffix(suffix),
        )


def archive_root_candidate(path: str | None) -> str | None:
    """Return the basename of a rendered path, or None for any other path.

    A candidate, not a guarantee: a caller must fall back when it does not resolve.
    """
    if not path:
        return None
    normalized = path.strip().replace("\\", "/")
    if not normalized or "/" not in normalized:
        return None
    basename = PurePosixPath(normalized).name
    return basename or None


def mime_type_for_suffix(path: str | None) -> str:
    """Return the MIME type a document path declares, or the octet-stream default.

    A slash path is a rendering, so it is named by the suffix its basename carries.
    """
    if not path:
        return DEFAULT_MIME
    normalized = path.strip().replace("\\", "/")
    if not normalized:
        return DEFAULT_MIME
    return MIME_BY_SUFFIX.get(_normalized_suffix(normalized), DEFAULT_MIME)


__all__ = [
    "BINARY_SUFFIXES",
    "DEFAULT_MIME",
    "DocumentPathFacts",
    "DocumentPathShape",
    "DocumentSuffixClass",
    "MARKUP_SUFFIXES",
    "MIME_BY_SUFFIX",
    "OPAQUE_SUFFIXES",
    "PAPER_SUFFIX",
    "TEXT_SUFFIXES",
    "XML_SUFFIXES",
    "archive_root_candidate",
    "mime_type_for_suffix",
]
