"""Corpus extraction: carried TOC span consumption and region stamps."""

from __future__ import annotations

from tools.table_extraction_corpus.extract import extract_filing

_HTML_10K = """<html><body>
<p>UNITED STATES SECURITIES AND EXCHANGE COMMISSION</p>
<p>FORM 10-K</p>
<p>ACME CORPORATION</p>
<p>TABLE OF CONTENTS</p>
<table><tr><td>PART I</td><td>1</td></tr>
<tr><td>ITEM 1. BUSINESS</td><td>1</td></tr>
<tr><td>ITEM 1A. RISK FACTORS</td><td>8</td></tr>
<tr><td>ITEM 2. PROPERTIES</td><td>14</td></tr></table>
<p>PART I</p>
<p>ITEM 1. BUSINESS</p>
<p>Acme is a leading provider of widgets.</p>
<table><tr><td>Cash</td><td>100</td></tr><tr><td>Total assets</td><td>500</td></tr></table>
</body></html>"""


def _spec() -> dict:
    return {
        "accession": "0000000000-24-000001",
        "cik": 1,
        "form": "10-K",
        "filing_date": "2024-03-01",
        "era": "modern",
        "is_xbrl": False,
        "labels": [],
    }


def test_extract_stamps_regions_and_toc_membership() -> None:
    record, _entries, _timing = extract_filing(
        _spec(), _HTML_10K.encode(), "acme.htm", tree="test"
    )

    geometries = record["geometries"]
    assert len(geometries) == 2
    for geometry in geometries:
        assert geometry["region"] in {"body", "cover", "signature", "exhibit"}
        assert geometry["region_path"] == "derived"
    toc_flags = {g["table_index"]: g["in_toc_span"] for g in geometries}
    assert toc_flags[geometries[0]["table_index"]] is True
    assert toc_flags[geometries[1]["table_index"]] is False
