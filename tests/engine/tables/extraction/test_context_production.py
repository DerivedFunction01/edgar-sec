"""Context production: carried facts, closing stamps, region map."""

from __future__ import annotations

from edgar_sec.engine.document.page_markers.models import PageArtifactPolicy
from edgar_sec.engine.forms.normalize import normalize_document
from edgar_sec.engine.tables.extraction.classify import classify_table
from edgar_sec.engine.tables.extraction.context import TableContext
from edgar_sec.engine.tables.extraction.context_production import (
    DocumentInput,
    FilingFacts,
    produce_contexts,
)
from edgar_sec.engine.tables.extraction.typed_rows import structure_table

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
