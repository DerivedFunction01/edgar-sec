"""PDF text extraction for the render_to_txt capability.

Pages extract one at a time and join on a page marker. A document with
no font resources anywhere has no text layer by construction, so it
shortcuts to an empty yield instead of paying a full extraction walk.
"""

from __future__ import annotations

from dataclasses import dataclass

import pymupdf

_PDF_MAGIC = b"%PDF-"
_PAGE_SEPARATOR = "\n<page>\n"
_PROBE_PAGE_LIMIT = 16
_PROBE_STRIDE = 16
_MIN_PROBE_YIELD = 100


class PdfConversionError(ValueError):
    """Source bytes are not a readable PDF."""


@dataclass(frozen=True, slots=True)
class PdfConversion:
    text: str
    page_count: int
    empty_yield: bool


def convert_pdf_to_text(raw_bytes: bytes) -> PdfConversion:
    """Extract a PDF's text layer, or refuse bytes that are not a PDF."""
    if not raw_bytes.startswith(_PDF_MAGIC):
        raise PdfConversionError("source does not carry PDF magic bytes")
    try:
        document = pymupdf.open(stream=raw_bytes, filetype="pdf")
    except Exception as error:
        raise PdfConversionError("source is not a readable PDF") from error
    with document:
        try:
            return _extract(document)
        except PdfConversionError:
            raise
        except Exception as error:
            raise PdfConversionError("source is not a readable PDF") from error


def _extract(document: pymupdf.Document) -> PdfConversion:
    page_count = document.page_count
    if not _has_text_layer(document, page_count):
        return PdfConversion("", page_count, True)
    probed = {
        page: document[page].get_text() for page in _probe_indices(page_count)
    }
    if sum(len(text) for text in probed.values()) < _MIN_PROBE_YIELD:
        return PdfConversion("", page_count, True)
    text = _PAGE_SEPARATOR.join(
        probed[page] if page in probed else document[page].get_text()
        for page in range(page_count)
    )
    return PdfConversion(text, page_count, False)


def _has_text_layer(document: pymupdf.Document, page_count: int) -> bool:
    return any(document[page].get_fonts(full=True) for page in range(page_count))


def _probe_indices(page_count: int) -> tuple[int, ...]:
    indices = list(range(min(3, page_count)))
    indices.extend(range(15, page_count, _PROBE_STRIDE))
    return tuple(indices[:_PROBE_PAGE_LIMIT])


__all__ = [
    "PdfConversion",
    "PdfConversionError",
    "convert_pdf_to_text",
]
