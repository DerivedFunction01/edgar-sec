"""Tests for multi-modal rendering dispatcher."""

import pytest
from edgar_sec.domain.document.aggregate import FilingAggregate
from edgar_sec.domain.forms.common.processing import AcquisitionOperation
from edgar_sec.domain.identity import AccessionNumber, Cik
from edgar_sec.engine.forms.render import (
    UnsupportedRenderOperation,
    render_document,
    render_filing,
)

SAMPLE_XML_FORM4 = b"""<?xml version="1.0"?>
<ownershipDocument>
    <issuer><issuerName>Apple Inc.</issuerName></issuer>
</ownershipDocument>"""

SAMPLE_HTML_10K = b"""<html>
<body>
<div>UNITED STATES SECURITIES AND EXCHANGE COMMISSION</div>
<div>FORM 10-K</div>
<p>Business overview and annual financial discussion.</p>
</body>
</html>"""


def test_render_document_10k_text() -> None:
    result = render_document(SAMPLE_HTML_10K, form="10-K", filename="doc.htm")
    assert isinstance(result, str)
    assert "UNITED STATES SECURITIES AND EXCHANGE COMMISSION" in result


def test_render_document_form4_xml() -> None:
    result = render_document(SAMPLE_XML_FORM4, form="4", filename="form4.xml")
    assert isinstance(result, str)
    assert "<ownershipDocument>" in result
    assert "Apple Inc." in result


def test_render_document_refuses_cross_modal() -> None:
    with pytest.raises(UnsupportedRenderOperation, match="does not support XML"):
        render_document(
            SAMPLE_HTML_10K,
            form="10-K",
            operation=AcquisitionOperation.RENDER_TO_XML,
        )

    with pytest.raises(UnsupportedRenderOperation, match="does not support text"):
        render_document(
            SAMPLE_XML_FORM4,
            form="4",
            operation=AcquisitionOperation.RENDER_TO_TXT,
        )


def test_render_document_raw_pass_through() -> None:
    binary_data = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
    result = render_document(binary_data, form="UNKNOWN", filename="image.png")
    assert result == binary_data


def test_render_filing_dispatch() -> None:
    filing = FilingAggregate(
        accession=AccessionNumber.from_any("0000320193-25-000079"),
        primary_cik=Cik.from_raw("0000320193"),
        ciks=(Cik.from_raw("0000320193"),),
        form="10-K",
        filing_date="2025-10-31",
        fetcher=lambda _f: SAMPLE_HTML_10K,
    )
    rendered = render_filing(filing)
    assert isinstance(rendered, str)
    assert "FORM 10-K" in rendered
