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

    # Topology evidence is published in metadata, JSON-serializable.
    topology_keys = (
        "cover_boundary_method",
        "cover_boundary_line",
        "cover_boundary_confidence",
        "cover_boundary_start_line",
        "toc_start_line",
        "toc_end_line",
        "body_start_line",
        "body_anchor_type",
        "body_confidence",
        "closing_start_line",
        "closing_kind",
        "closing_confidence",
    )
    for key in topology_keys:
        assert key in processed.metadata, key

    # This document has no standalone SIGNATURES heading or /s/ line, so the
    # closing region must remain undetected rather than guessed.
    assert processed.metadata["closing_start_line"] is None
    assert processed.metadata["closing_kind"] is None


def test_default_filing_processor_persists_topology_metadata(tmp_path) -> None:
    from defs.sql import Commit, insert_values, make_sql_executor

    processor = DefaultFilingProcessor()

    raw_ascii = b"""<DOCUMENT>
<TYPE>10-K
<TEXT>
FORM 10-K

ANNUAL REPORT PURSUANT TO SECTION 13

Registrant: Example Corp
State of Incorporation: Delaware

TABLE OF CONTENTS

PART I
Item 1. Business ................. 1
Item 1A. Risk Factors ............ 5

PART I
ITEM 1. BUSINESS

We are an enterprise software company founded in 1998.
Our customers include major healthcare providers and suppliers.
The company operates manufacturing facilities worldwide
and sells products across multiple market segments.

MANAGEMENT'S DISCUSSION AND ANALYSIS

The following table summarizes the revenue:

Revenue by segment       2024       2023
  Automotive             $1,200     $1,100
  Industrial              $2,050     $1,980
  Total                  $3,250     $3,080

SIGNATURES

Pursuant to the requirements of Section 13, this report has been
signed below by the following persons on behalf of the Registrant.

Date: March 1, 1999
By: /s/ Jane Doe
Title: Chief Executive Officer
</TEXT>
</DOCUMENT>"""

    locator = DocumentLocator(
        locator_key="k2",
        accession="0000123456-98-000001",
        document_path="form10k.txt",
        archive_url="https://www.sec.gov/Archives/edgar/data/123456/000012345698000001/form10k.txt",
        form="10-K",
    )

    processed = asyncio.run(processor.process(raw_ascii, locator))
    meta = processed.metadata

    assert meta["cover_boundary_line"] is not None
    assert meta["cover_boundary_start_line"] is not None
    assert meta["body_start_line"] is not None
    assert meta["body_anchor_type"] in {"structural", "semantic", "substantive"}
    assert meta["body_confidence"] is not None
    assert isinstance(meta["body_rejection_reasons"], list)

    # The SIGNATURES heading after the body is published as closing evidence.
    assert meta["closing_start_line"] is not None
    assert meta["closing_kind"] == "signatures"
    assert meta["closing_confidence"] is not None

    # The hard-wrapped body paragraph was unwrapped; reflow counts published.
    decoded_ascii = processed.payload.decode("utf-8")
    assert (
        "We are an enterprise software company founded in 1998. "
        "Our customers include major healthcare providers and suppliers."
    ) in decoded_ascii
    assert meta["reflow_unwrap_blocks"] >= 1

    # The untagged ASCII financial table was protected with canonical tags
    # and its rows preserved exactly.
    assert "<TABLE>" in decoded_ascii
    assert "</TABLE>" in decoded_ascii
    assert "Revenue by segment       2024       2023" in decoded_ascii
    assert "  Total                  $3,250     $3,080" in decoded_ascii
    assert meta["reflow_tag_blocks"] == 1

    import json

    encoded = json.dumps(meta, sort_keys=True)
    assert json.loads(encoded)["body_start_line"] == meta["body_start_line"]
    assert json.loads(encoded)["closing_start_line"] == meta["closing_start_line"]

    database = tmp_path / "metadata.db"
    database.touch()
    executor = make_sql_executor(database, dialect="sqlite")
    try:
        schemas.create_chunk_schema(executor)
        executor.exec(
            executor.compiler.compile(
                insert_values(
                    schemas.NORMALIZED_DOCUMENTS_TABLE,
                    {
                        "normalized_artifact_id": "artifact-1",
                        "source_doc_id": "doc-1",
                        "byte_size": processed.byte_size,
                        "normalized_payload": processed.payload,
                        "payload_sha256": "0" * 64,
                        "mime_type": "text/plain",
                        "representation": "normalized-text",
                        "processor_fingerprint": "default-filing-processor:v1",
                        "schema_version": schemas.NORMALIZED_SCHEMA_VERSION,
                        "processor_metadata": schemas.deterministic_metadata(meta),
                    },
                )
            )
        )
        executor.exec(executor.compiler.compile(Commit()))
    finally:
        executor.close()
