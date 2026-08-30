"""Tests for DefaultFilingProcessor end-to-end pipeline."""

from __future__ import annotations

import asyncio
import importlib

schemas = importlib.import_module("phases.025_webpage_storage.core.schemas")
processors = importlib.import_module("phases.025_webpage_storage.processors")

DocumentLocator = schemas.DocumentLocator
DefaultFilingProcessor = processors.DefaultFilingProcessor


def test_default_filing_processor_lifecycle() -> None:
    processor = DefaultFilingProcessor()

    raw_html = b"""<DOCUMENT>
<TYPE>10-K
<TEXT>
<html>
<body>
<p>ITEM 1. BUSINESS</p>
<p>We are an enterprise software company.</p>
<table>
  <tr><th>Metric</th><th>Value</th></tr>
  <tr><td>ARR</td><td>$50M</td></tr>
</table>
<PAGE>
<p>Page 1 of 5</p>
<p>ITEM 7. MD&A</p>
<p>Revenues grew 40% year over year.</p>
</body>
</html>
</TEXT>
</DOCUMENT>"""

    locator = DocumentLocator(
        locator_key="k1",
        accession="0000123456-02-000001",
        document_path="form10k.htm",
        archive_url="https://www.sec.gov/Archives/edgar/data/123456/000012345602000001/form10k.htm",
        form="10-K",
    )

    processed = asyncio.run(processor.process(raw_html, locator))

    assert processed.byte_size > 0
    assert processed.metadata["is_stub"] is False
    assert processed.metadata["decision_action"] == "proceed"
    assert processed.metadata["word_count"] >= 10

    decoded_text = processed.payload.decode("utf-8")
    assert "ITEM 1. BUSINESS" in decoded_text
    assert "ITEM 7. MD&A" in decoded_text
    assert "<PAGE>" not in decoded_text
    assert "ARR" in decoded_text
