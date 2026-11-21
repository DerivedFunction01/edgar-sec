from __future__ import annotations

import xml.etree.ElementTree as ET

from edgar_sec.engine.forms.beneficial_ownership.provenance_analysis import (
    analyze_extraction_provenance,
)


def test_provenance_analysis_validates_field_map_and_residual_coverage() -> None:
    source = "Alice loose"
    root = ET.fromstring(
        "<edgarSubmission><formData><issuerName>Alice</issuerName></formData>"
        '<extractionProvenance sourceLength="11">'
        '<fieldExtraction fieldPath="formData.issuerName" startOffset="0" '
        'endOffset="5"><sourceText>Alice</sourceText></fieldExtraction>'
        "</extractionProvenance>"
        '<unparsedSections sourceLength="11">'
        '<unparsedSection startOffset="6" endOffset="11" role="unparsed">'
        "loose</unparsedSection></unparsedSections></edgarSubmission>"
    )

    anomalies, coverage = analyze_extraction_provenance(
        root, source, "a", required=True
    )

    assert anomalies == []
    assert coverage == {
        "source_length": 11,
        "source_nonwhitespace_characters": 10,
        "mapped_nonwhitespace_characters": 5,
        "unparsed_nonwhitespace_characters": 5,
        "uncovered_nonwhitespace_characters": 0,
        "field_extraction_count": 1,
    }


def test_provenance_analysis_detects_missing_field_target_and_source_gap() -> None:
    source = "Alice lost"
    root = ET.fromstring(
        "<edgarSubmission><formData><issuerName>Alice</issuerName></formData>"
        '<extractionProvenance sourceLength="10">'
        '<fieldExtraction fieldPath="formData.noticeContact" startOffset="0" '
        'endOffset="5"><sourceText>Alice</sourceText></fieldExtraction>'
        "</extractionProvenance>"
        '<unparsedSections sourceLength="10"/>'
        "</edgarSubmission>"
    )

    anomalies, coverage = analyze_extraction_provenance(
        root, source, "a", required=True
    )

    assert {item["kind"] for item in anomalies} == {
        "field_extraction_target_missing",
        "uncovered_source_text",
    }
    assert coverage is not None
    assert coverage["uncovered_nonwhitespace_characters"] == 4


def test_provenance_analysis_requires_diagnostics_only_for_converted_documents() -> (
    None
):
    root = ET.fromstring("<edgarSubmission />")

    anomalies, coverage = analyze_extraction_provenance(
        root, "native source", "a", required=False
    )

    assert anomalies == []
    assert coverage is None

    anomalies, coverage = analyze_extraction_provenance(
        root, "converted source", "b", required=True
    )

    assert [item["kind"] for item in anomalies] == ["missing_extraction_provenance"]
    assert coverage is None
