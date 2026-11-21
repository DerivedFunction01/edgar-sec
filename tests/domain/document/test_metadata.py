"""Tests for document payload metadata detection and operational classification."""

from __future__ import annotations

from edgar_sec.domain.document.metadata import (
    PayloadMetadata,
    detect_raw_metadata,
    detect_render_metadata,
)
from edgar_sec.domain.document.path_facts import DocumentSuffixClass
from edgar_sec.domain.forms.common.processing import AcquisitionOperation


def test_detect_raw_metadata_markup_formats() -> None:
    meta_htm = detect_raw_metadata("d12345.htm")
    assert meta_htm.suffix_class == DocumentSuffixClass.MARKUP
    assert meta_htm.suffix == ".htm"
    assert meta_htm.format_name == "htm"
    assert meta_htm.content_type == "text/html"
    assert not meta_htm.is_binary
    assert meta_htm.operation == "raw"

    meta_html = detect_raw_metadata("primary/report.html")
    assert meta_html.suffix_class == DocumentSuffixClass.MARKUP
    assert meta_html.format_name == "html"
    assert meta_html.content_type == "text/html"


def test_detect_raw_metadata_xml_and_text() -> None:
    meta_xml = detect_raw_metadata("form4.xml")
    assert meta_xml.suffix_class == DocumentSuffixClass.XML
    assert meta_xml.format_name == "xml"
    assert meta_xml.content_type == "text/xml"
    assert not meta_xml.is_binary

    meta_txt = detect_raw_metadata("filing.txt")
    assert meta_txt.suffix_class == DocumentSuffixClass.TEXT
    assert meta_txt.format_name == "txt"
    assert meta_txt.content_type == "text/plain"
    assert not meta_txt.is_binary


def test_detect_raw_metadata_binary_and_pdf() -> None:
    meta_pdf = detect_raw_metadata("ex99-1.pdf")
    assert meta_pdf.suffix_class == DocumentSuffixClass.PDF
    assert meta_pdf.format_name == "pdf"
    assert meta_pdf.content_type == "application/pdf"
    assert meta_pdf.is_binary

    meta_jpg = detect_raw_metadata("chart.jpg")
    assert meta_jpg.suffix_class == DocumentSuffixClass.IMAGE
    assert meta_jpg.format_name == "jpg"
    assert meta_jpg.content_type == "image/jpeg"
    assert meta_jpg.is_binary


def test_detect_render_metadata_operation_explicit() -> None:
    raw_meta = detect_raw_metadata("d12345.htm")

    render_xml = detect_render_metadata("4", raw_meta, operation="xml")
    assert render_xml.suffix_class == DocumentSuffixClass.XML
    assert render_xml.format_name == "xml"
    assert render_xml.content_type == "text/xml"
    assert render_xml.operation == AcquisitionOperation.RENDER_TO_XML.value

    render_txt = detect_render_metadata("10-K", raw_meta, operation="render_to_txt")
    assert render_txt.suffix_class == DocumentSuffixClass.TEXT
    assert render_txt.format_name == "txt"
    assert render_txt.content_type == "text/plain"
    assert render_txt.operation == AcquisitionOperation.RENDER_TO_TXT.value

    render_raw = detect_render_metadata("4", raw_meta, operation="raw")
    assert render_raw.suffix_class == DocumentSuffixClass.MARKUP
    assert render_raw.format_name == "htm"
    assert render_raw.content_type == "text/html"
    assert render_raw.operation == AcquisitionOperation.RAW.value


def test_detect_render_metadata_profile_defaults() -> None:
    raw_meta = detect_raw_metadata("d12345.htm")

    # Form 4 preferred operation is RENDER_TO_XML
    render_form4 = detect_render_metadata("4", raw_meta)
    assert render_form4.suffix_class == DocumentSuffixClass.XML
    assert render_form4.format_name == "xml"
    assert render_form4.operation == AcquisitionOperation.RENDER_TO_XML.value

    # Form 10-K preferred operation is RENDER_TO_TXT
    render_10k = detect_render_metadata("10-K", raw_meta)
    assert render_10k.suffix_class == DocumentSuffixClass.TEXT
    assert render_10k.format_name == "txt"
    assert render_10k.operation == AcquisitionOperation.RENDER_TO_TXT.value
