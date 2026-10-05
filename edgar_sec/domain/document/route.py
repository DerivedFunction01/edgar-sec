"""How one document path is stored and normalized, decided before any bytes are read.

A slash outranks the suffix: EDGAR publishes an XSL rendering under ``xsl<Form>X01/``
named ``.xml`` while serving HTML, so every slash path in the corpus is a rendering
and a flat suffix is the only decisive signal.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import PurePosixPath

#: Flat suffixes carrying markup. Anything with a slash is HTML regardless of this.
MARKUP_SUFFIXES = frozenset({".htm", ".html", ".xhtml"})

#: Flat suffixes carrying text.
TEXT_SUFFIXES = frozenset({".txt"})

#: Flat suffixes carrying an XML-native filing's own markup.
XML_SUFFIXES = frozenset({".xml"})

#: Flat suffixes that are binary regardless of what the document means.
BINARY_SUFFIXES = frozenset({".pdf", ".gif", ".jpg"})

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
}

DEFAULT_MIME = "application/octet-stream"

#: Flat suffix of an EDGAR paper submission. The served payload is a fixed SGML
#: stub pointing at an off-archive Document Control Number, never filing prose.
PAPER_SUFFIX = ".paper"

#: Representation names a normalized document reports.
REPRESENTATION_ASCII = "ascii"
REPRESENTATION_HTML = "html"
REPRESENTATION_XML = "xml"
REPRESENTATION_RAW = "raw"


class DocumentRoute(StrEnum):
    """The acquisition and normalization route one document path selects."""

    #: Inside an XSL rendering directory; the original lives at the archive root.
    RENDERED = "rendered"
    #: Flat markup, served as-is.
    MARKUP = "markup"
    #: Flat text, normalized as prose.
    TEXT = "text"
    #: Fixed SGML stub with no filing content.
    PAPER = "paper"
    #: Flat XML-native document.
    XML = "xml"
    #: Flat binary; never text.
    BINARY = "binary"
    #: Flat path with no established rule. Treated as text.
    UNKNOWN = "unknown"


#: Routes whose payload EDGAR serves as markup.
_MARKUP_ROUTES = frozenset({DocumentRoute.MARKUP, DocumentRoute.RENDERED})


def _normalized_suffix(document_path: str) -> str:
    """Return the case-folded suffix of a path under EDGAR's separator spelling."""
    return PurePosixPath(document_path.strip().replace("\\", "/")).suffix.casefold()


def _route_for_suffix(suffix: str) -> DocumentRoute:
    """Classify an already-extracted suffix, with no directory consulted."""
    if suffix in MARKUP_SUFFIXES:
        return DocumentRoute.MARKUP
    if suffix in TEXT_SUFFIXES:
        return DocumentRoute.TEXT
    if suffix == PAPER_SUFFIX:
        return DocumentRoute.PAPER
    if suffix in XML_SUFFIXES:
        return DocumentRoute.XML
    if suffix in BINARY_SUFFIXES:
        return DocumentRoute.BINARY
    return DocumentRoute.UNKNOWN


def document_route(document_path: str | None) -> DocumentRoute:
    """Classify one document path.

    A slash selects ``RENDERED`` before the suffix is consulted, so a rendering
    named ``.xml`` is HTML. A flat path is classified by suffix alone.
    """
    if not document_path:
        return DocumentRoute.UNKNOWN

    normalized = document_path.strip().replace("\\", "/")
    if not normalized:
        return DocumentRoute.UNKNOWN

    if "/" in normalized:
        return DocumentRoute.RENDERED

    return _route_for_suffix(_normalized_suffix(normalized))


def content_route(document_path: str | None) -> DocumentRoute:
    """Classify already-acquired content by suffix alone, ignoring any directory.

    A slash means "XSL rendering" for a published URL, not for an SGML
    ``<FILENAME>``: only a caller holding such a basename may pass it here.
    """
    if not document_path:
        return DocumentRoute.UNKNOWN
    return _route_for_suffix(_normalized_suffix(document_path))


def mime_type_for_suffix(document_path: str | None) -> str:
    """Return the MIME type a document path declares, or the octet-stream default.

    A slash path is a rendering, so it is named by the suffix its basename carries.
    """
    if not document_path:
        return DEFAULT_MIME
    normalized = document_path.strip().replace("\\", "/")
    if not normalized:
        return DEFAULT_MIME
    return MIME_BY_SUFFIX.get(_normalized_suffix(normalized), DEFAULT_MIME)


def is_rendered_document_path(document_path: str | None) -> bool:
    """Whether the path names an XSL rendering whose original sits at the archive root."""
    return document_route(document_path) is DocumentRoute.RENDERED


def is_markup_document_path(document_path: str | None) -> bool:
    """Whether the path names a document EDGAR serves as markup.

    A rendering counts, because it lives under a directory yet is served as HTML
    whatever its basename is named; a caller keying on the suffix alone misses it.
    """
    return document_route(document_path) in _MARKUP_ROUTES


def archive_root_candidate(document_path: str | None) -> str | None:
    """Return the basename of a rendered path, or ``None`` for any other path.

    A candidate, not a guarantee: a caller must fall back when it does not resolve.
    """
    if not is_rendered_document_path(document_path):
        return None
    basename = PurePosixPath(document_path.strip().replace("\\", "/")).name
    return basename or None


__all__ = [
    "BINARY_SUFFIXES",
    "DEFAULT_MIME",
    "MARKUP_SUFFIXES",
    "MIME_BY_SUFFIX",
    "PAPER_SUFFIX",
    "REPRESENTATION_ASCII",
    "REPRESENTATION_HTML",
    "REPRESENTATION_RAW",
    "REPRESENTATION_XML",
    "TEXT_SUFFIXES",
    "XML_SUFFIXES",
    "DocumentRoute",
    "archive_root_candidate",
    "content_route",
    "document_route",
    "is_markup_document_path",
    "is_rendered_document_path",
    "mime_type_for_suffix",
]
