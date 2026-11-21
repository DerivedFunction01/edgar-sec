"""Normalize representation routing, reflow, and route refusals."""

from __future__ import annotations

import pytest

from edgar_sec.engine.forms.normalize import normalize_document
from tests.support.fixtures import load_fixture

from tests.engine.forms.normalize_support import (
    _HARD_WRAPPED,
    _PAPER_STUB,
    _PDF_BYTES,
    _TAGGED_TABLE_TOC,
)


def test_no_cover_ascii_reflows_from_line_zero() -> None:
    """No cover structure means no detected body start, so reflow must still run."""
    res = normalize_document(_HARD_WRAPPED, form="REGDEX", document_path="note.txt")

    assert res.reflow is not None
    assert len(res.text.splitlines()) == 1
    assert "Securities Exchange Act of 1934, as amended." in res.text


def test_cover_bearing_family_keeps_detected_body_offset() -> None:
    data = load_fixture("document_storage/annual_10k_normalization.json")
    raw_bytes = data["source_text"].encode("utf-8")

    res = normalize_document(raw_bytes, form="10-K", document_path="annual.txt")

    assert res.body_start is not None
    assert res.body_start.first_unit_line is not None
    assert res.body_start.first_unit_line > 0


def test_rendered_path_is_not_treated_as_xml() -> None:
    """An XSL rendering is named ``.xml`` but serves markup, and must not be read as XML."""
    payload = b"<HTML><BODY><TABLE><TR><TD>OWNERSHIP</TD></TR></TABLE></BODY></HTML>"

    res = normalize_document(payload, form="4", document_path="xslF345X03/doc4.xml")

    assert res.representation == "html"


def test_toc_span_source_carries_the_found_span() -> None:
    """The source-frame span is the finder's result, before reflow (DR-2)."""
    res = normalize_document(
        _TAGGED_TABLE_TOC.encode(), form="10-K", document_path="acme.txt"
    )

    assert res.page_analysis is not None
    source_lines = res.page_analysis.source_text.splitlines()
    span = res.toc_span_source
    assert span is not None
    assert source_lines[span.start_line] == "TABLE OF CONTENTS"
    assert source_lines[span.end_line - 1] == "</TABLE>"
    assert res.page_analysis.source_text[span.start_offset : span.end_offset] == (
        "\n".join(source_lines[span.start_line : span.end_line]) + "\n"
    )


def test_toc_span_source_absent_without_toc() -> None:
    """No TOC found in normalize means no carried source span (DR-2)."""
    res = normalize_document(
        b"FORM 10-K\nACME\nPART I\nITEM 1. BUSINESS\nAcme provides widgets.\n",
        form="10-K",
        document_path="acme.txt",
    )

    assert res.toc_span is None
    assert res.toc_span_source is None
    assert res.reflow is None


def test_markup_path_without_markup_is_normalized_as_text() -> None:
    """A ``.htm`` path whose bytes carry no markup is still ASCII; the payload decides."""
    res = normalize_document(_HARD_WRAPPED, form="REGDEX", document_path="note.htm")

    assert res.representation == "ascii"
    assert res.reflow is None


def test_flat_xml_path_is_not_text() -> None:
    payload = b'<?xml version="1.0"?><ownershipDocument><x>1</x></ownershipDocument>'

    res = normalize_document(payload, form="4", document_path="ownership.xml")

    assert res.representation == "xml"
    assert res.reflow is None


def test_markup_route_is_not_reflowed() -> None:
    res = normalize_document(_HARD_WRAPPED, form="REGDEX", document_path="note.htm")

    assert res.reflow is None


def test_paper_route_skips_form_driven_stages() -> None:
    res = normalize_document(
        _PAPER_STUB, form="REGDEX", document_path="9999999997-25-001505.paper"
    )

    assert res.representation == "ascii"
    assert res.reflow is None
    assert res.body_start is None
    assert res.cover_boundary.method.value == "disabled"
    assert "Document Control Number 25000522" in res.text


def test_binary_route_is_refused() -> None:
    """There is no text form of a PDF, so normalization must refuse rather than invent one."""
    with pytest.raises(ValueError, match="binary"):
        normalize_document(_PDF_BYTES, form="8-K", document_path="chart.pdf")


def test_binary_refusal_names_the_route_and_the_remedy() -> None:
    """The message must tell the caller what to do, not that the route is unimplemented."""
    with pytest.raises(ValueError, match="verbatim"):
        normalize_document(_PDF_BYTES, form="8-K", document_path="chart.pdf")


def test_every_binary_suffix_is_refused() -> None:
    for suffix in (".pdf", ".gif", ".jpg"):
        with pytest.raises(ValueError):
            normalize_document(_PDF_BYTES, form="8-K", document_path=f"chart{suffix}")


def test_xhtml_path_is_markup_not_text() -> None:
    """``.xhtml`` is markup; treating it as unknown text would reflow it as prose."""
    res = normalize_document(_HARD_WRAPPED, form="REGDEX", document_path="note.xhtml")

    assert res.reflow is None
