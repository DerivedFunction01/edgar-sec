"""Unit tests for ownership review case analysis."""

from __future__ import annotations

from edgar_sec.engine.forms.common.xml.unparsed import serialize_unparsed_sections
from edgar_sec.engine.forms.ownership.analysis.case import (
    analyze_ownership_review_case,
)


def test_review_analysis_loads_common_sidecar(tmp_path) -> None:
    operations = tmp_path / "operations"
    operations.mkdir()
    (operations / "render_to_xml.xml").write_bytes(
        b"<ownershipDocument><documentType>4</documentType></ownershipDocument>"
    )
    (operations / "unparsed_sections.json").write_bytes(
        serialize_unparsed_sections(
            [
                {
                    "role": "unparsed",
                    "content_type": "text/html",
                    "content": "<table>review content</table>",
                    "table_index": 2,
                }
            ]
        )
    )

    report = analyze_ownership_review_case(tmp_path, {"accession": "a1"})

    assert report is not None
    assert report["unparsed_sections"][0]["table_index"] == "2"
    assert report["unparsed_sections"][0]["snippet"] == (
        "<table>review content</table>"
    )
