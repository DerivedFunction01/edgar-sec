"""Computed products survive a serialize/rebuild round trip."""

from __future__ import annotations

from edgar_sec.engine.document.page_markers.models import PageArtifactPolicy
from edgar_sec.engine.forms.normalize import normalize_document
from edgar_sec.engine.tables.extraction.assembly.context_production import (
    DocumentInput,
    produce_contexts,
)
from edgar_sec.pipelines.table_classification.fixture_store.products import (
    deserialize_result,
    serialize_result,
)

_HTML_10K = """<html><body>
<p>FORM 10-K</p>
<p>ACME CORPORATION</p>
<p>TABLE OF CONTENTS</p>
<table><tr><td>PART I</td><td>1</td></tr>
<tr><td>ITEM 1. BUSINESS</td><td>1</td></tr></table>
<p>PART I</p>
<p>ITEM 1. BUSINESS</p>
<p>Acme is a leading provider of widgets and employs many people.</p>
<table><tr><td>Cash</td><td>100</td></tr><tr><td>Total assets</td><td>500</td></tr></table>
<p>SIGNATURES</p>
<p>Pursuant to the requirements of Section 13 of the Act, the registrant has duly caused this report to be signed.</p>
<table><tr><td>/s/ Jane Doe</td><td>Chief Executive Officer</td></tr></table>
</body></html>"""


def _result():
    return normalize_document(
        _HTML_10K.encode(),
        form="10-K",
        document_path="acme.htm",
        page_policy=PageArtifactPolicy.ANNOTATE,
    )


def test_round_trip_preserves_products() -> None:
    result = _result()
    rebuilt = deserialize_result(serialize_result(result))
    assert rebuilt.text == result.text
    assert rebuilt.family == result.family
    assert len(rebuilt.table_geometries) == len(result.table_geometries)
    for mine, theirs in zip(
        rebuilt.table_geometries, result.table_geometries, strict=True
    ):
        assert mine.table_index == theirs.table_index
        assert mine.rows == theirs.rows
        assert mine.render_result.ascii_text == theirs.render_result.ascii_text
    assert rebuilt.toc_span_source is not None
    assert result.toc_span_source is not None
    assert rebuilt.toc_span_source.start_line == result.toc_span_source.start_line
    assert rebuilt.closing_span is not None
    assert result.closing_span is not None
    assert rebuilt.closing_span.kind == result.closing_span.kind


def test_rebuilt_products_reproduce_contexts() -> None:
    result = _result()
    rebuilt = deserialize_result(serialize_result(result))
    live = produce_contexts(DocumentInput("primary", result))
    replay = produce_contexts(DocumentInput("primary", rebuilt))
    assert replay.documents[0].records == live.documents[0].records
    assert len(replay.contexts) == len(live.contexts)
