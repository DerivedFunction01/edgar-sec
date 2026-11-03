"""Tests for the PDF text converter behind the text.pdf capability."""

from __future__ import annotations

import pytest

from edgar_sec.engine.document_processing.pdf import (
    PdfConversionError,
    convert_pdf_to_text,
)
from tests.support import make_pdf_bytes

_LONG_TEXT = " ".join(["Filed annual report text."] * 12)
_PAGE_ONE = "Statements of income for the year ended December thirty first."
_PAGE_TWO = "Statements of cash flows for the year ended December thirty first."


def test_extracts_each_page_joined_on_the_page_marker() -> None:
    conversion = convert_pdf_to_text(make_pdf_bytes([_PAGE_ONE, _PAGE_TWO]))

    assert conversion.page_count == 2
    assert not conversion.empty_yield
    assert conversion.text.index(_PAGE_ONE) < conversion.text.index("\n<page>\n")
    assert conversion.text.index("\n<page>\n") < conversion.text.index(_PAGE_TWO)


def test_document_with_no_fonts_shortcuts_to_empty_yield() -> None:
    conversion = convert_pdf_to_text(make_pdf_bytes([None, None]))

    assert conversion.page_count == 2
    assert conversion.empty_yield
    assert conversion.text == ""


def test_negligible_probe_yield_is_an_empty_yield() -> None:
    conversion = convert_pdf_to_text(make_pdf_bytes(["x"]))

    assert conversion.empty_yield
    assert conversion.text == ""


def test_text_beyond_the_probe_sample_is_a_bounded_miss() -> None:
    pages: list[str | None] = [None] * 19 + [_LONG_TEXT]

    conversion = convert_pdf_to_text(make_pdf_bytes(pages))

    assert conversion.page_count == 20
    assert conversion.empty_yield


def test_non_pdf_bytes_are_refused() -> None:
    with pytest.raises(PdfConversionError):
        convert_pdf_to_text(b"<html><body>not a pdf</body></html>")


def test_empty_bytes_are_refused() -> None:
    with pytest.raises(PdfConversionError):
        convert_pdf_to_text(b"")


def test_corrupt_pdf_bytes_are_refused() -> None:
    with pytest.raises(PdfConversionError):
        convert_pdf_to_text(b"%PDF-1.4\n" + bytes(range(256)) * 4)


def test_truncated_pdf_bytes_are_refused() -> None:
    with pytest.raises(PdfConversionError):
        convert_pdf_to_text(make_pdf_bytes([_LONG_TEXT])[:80])
