"""Context production: carried facts, closing stamps, region map."""

from __future__ import annotations

from edgar_sec.engine.document.page_markers.models import PageArtifactPolicy
from edgar_sec.engine.forms.cover.models import BoundaryMethod, CoverBoundary
from edgar_sec.engine.forms.normalize import NormalizationResult, normalize_document
from edgar_sec.engine.tables.ascii_html.model.model import (
    ResolvedGrid,
    TableGeometry,
    TableRenderResult,
)
from edgar_sec.engine.tables.extraction.cascade.scoring.classify import classify_table
from edgar_sec.engine.tables.extraction.core.text.context import TableContext
from edgar_sec.engine.tables.extraction.assembly.context_production import (
    DocumentInput,
    FilingFacts,
    produce_contexts,
)
from edgar_sec.engine.tables.extraction.core.typed_rows import structure_table

_HTML_10K = """<html><body>
<p>UNITED STATES SECURITIES AND EXCHANGE COMMISSION</p>
<p>FORM 10-K</p>
<p>ACME CORPORATION</p>
<p>TABLE OF CONTENTS</p>
<table><tr><td>PART I</td><td>1</td></tr>
<tr><td>ITEM 1. BUSINESS</td><td>1</td></tr>
<tr><td>ITEM 2. PROPERTIES</td><td>14</td></tr></table>
<p>PART I</p>
<p>ITEM 1. BUSINESS</p>
<p>Acme is a leading provider of widgets and employs many people.</p>
<table><tr><td>Cash</td><td>100</td></tr><tr><td>Total assets</td><td>500</td></tr></table>
<p>SIGNATURES</p>
<p>Pursuant to the requirements of Section 13 of the Act, the registrant has duly caused this report to be signed.</p>
<table><tr><td>/s/ Jane Doe</td><td>Chief Executive Officer</td></tr></table>
</body></html>"""


def _production():
    result = normalize_document(
        _HTML_10K.encode(),
        form="10-K",
        document_path="acme.htm",
        page_policy=PageArtifactPolicy.ANNOTATE,
    )
    return produce_contexts(DocumentInput("primary", result))


def test_facts_carry_closing_span_and_region_map() -> None:
    production = _production()
    facts = production.documents[0].facts
    assert facts.source_document == "primary"
    assert facts.closing_start is not None
    assert facts.closing_kind == "signatures"
    seats = {seat.seat for seat in facts.region_map}
    assert "item_1" in seats
    record = facts.as_record()
    assert record["closing_kind"] == "signatures"
    assert record["region_map"]


def test_contexts_carry_source_and_closing_stamps() -> None:
    production = _production()
    contexts = production.documents[0].contexts
    assert len(contexts) == 3
    assert all(context.source_document == "primary" for context in contexts)
    closing = [context for context in contexts if context.in_closing_span]
    assert len(closing) == 1
    assert closing[0].closing_kind == "signatures"
    assert all(
        context.region is not None and context.region_path == "derived"
        for context in contexts
    )
    records = production.documents[0].records
    assert records[-1]["in_closing_span"] is True
    assert records[-1]["source_document"] == "primary"
    assert records[0]["in_closing_span"] is False


def test_contexts_carry_the_region_map_seat() -> None:
    production = _production()
    contexts = production.documents[0].contexts
    seats = [context.seat for context in contexts]
    assert "item_1" in seats
    records = production.documents[0].records
    assert [record["seat"] for record in records] == seats
    business = next(context for context in contexts if context.seat == "item_1")
    record = records[contexts.index(business)]
    restored = TableContext.from_record(business.geometry, record)
    assert restored.seat == "item_1"


def test_closing_span_table_is_genre_refused() -> None:
    production = _production()
    closing = next(
        context
        for context in production.documents[0].contexts
        if context.in_closing_span
    )
    result = classify_table(structure_table(closing))
    assert result.tier == "genre_refusal"
    assert result.family == "other"
    assert any(
        evidence.detail.startswith("closing refused") for evidence in result.evidence
    )


def _geometry(index: int, rows: tuple, rendered: str) -> TableGeometry:
    return TableGeometry(
        table_index=index,
        render_result=TableRenderResult(
            ascii_text=rendered,
            resolved_grid=ResolvedGrid(
                rows=rows,
                column_alignments=(),
                column_widths=(),
                header_row_count=0,
            ),
            confidence=1.0,
        ),
    )


_COVER_ROWS = (
    ("Title of each class", "Trading Symbol"),
    ("Common Stock", "ACME"),
)
_BODY_ROWS = (
    ("Cash", "100"),
    ("Total assets", "500"),
)
_SPLIT_TEXT = "\n".join(
    (
        "ACME CORPORATION",
        "Title of each class | Trading Symbol",
        "Common Stock | ACME",
        "PART I",
        "ITEM 1. BUSINESS",
        "Cash | 100",
        "Total assets | 500",
    )
)


def _split_production(family: str, end_line: int | None):
    result = NormalizationResult(
        text=_SPLIT_TEXT,
        family=family,
        representation="html",
        cover_boundary=CoverBoundary(
            end_line=end_line,
            end_offset=None,
            method=BoundaryMethod.STRUCTURAL,
            confidence=1.0,
        ),
        table_geometries=(
            _geometry(
                0,
                _COVER_ROWS,
                "Title of each class | Trading Symbol\nCommon Stock | ACME",
            ),
            _geometry(1, _BODY_ROWS, "Cash | 100\nTotal assets | 500"),
        ),
    )
    return produce_contexts(DocumentInput("primary", result))


def test_cover_boundary_split_excludes_pre_boundary_geometry_10k() -> None:
    production = _split_production("10-K", 3)
    document = production.documents[0]
    assert document.facts.cover_end_line == 3
    assert document.facts.as_record()["cover_end_line"] == 3
    assert document.cover_excluded == (0,)
    assert [context.table_index for context in document.contexts] == [1]
    assert [record["table_index"] for record in document.records] == [1]


def test_cover_boundary_split_excludes_pre_boundary_geometry_10q() -> None:
    production = _split_production("10-Q", 3)
    document = production.documents[0]
    assert document.cover_excluded == (0,)
    assert [context.table_index for context in document.contexts] == [1]


def test_no_cover_boundary_keeps_every_geometry() -> None:
    production = _split_production("10-K", None)
    document = production.documents[0]
    assert document.cover_excluded == ()
    assert [context.table_index for context in document.contexts] == [0, 1]


def test_unlocated_geometry_stays_in_the_input() -> None:
    result = NormalizationResult(
        text=_SPLIT_TEXT,
        family="10-K",
        representation="html",
        cover_boundary=CoverBoundary(
            end_line=3,
            end_offset=None,
            method=BoundaryMethod.STRUCTURAL,
            confidence=1.0,
        ),
        table_geometries=(
            _geometry(0, _COVER_ROWS, "Title of each class | Trading Symbol\nCommon Stock | ACME"),
            _geometry(7, _BODY_ROWS, "Not present | 0"),
        ),
    )
    document = produce_contexts(DocumentInput("primary", result)).documents[0]
    assert document.cover_excluded == (0,)
    assert document.not_located == (7,)
    assert [context.table_index for context in document.contexts] == [7]


def test_facts_from_result_without_closing_span() -> None:
    result = normalize_document(
        b"<html><body><p>FORM 10-K</p><p>plain body text</p></body></html>",
        form="10-K",
        document_path="plain.htm",
        page_policy=PageArtifactPolicy.ANNOTATE,
    )
    facts = FilingFacts.from_result(result, "primary")
    assert facts.closing_start is None
    assert facts.closing_kind is None
