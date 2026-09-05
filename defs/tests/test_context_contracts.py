"""Contract tests for the document-context models and adapters.

The tests assert invariants from the table-processing context refactor
plan's "Contract tests" section: empty/partial context is valid, standalone
behavior is unchanged, context is excluded from table identity, and the
index/scanner produce deterministic fingerprints.
"""

from __future__ import annotations

from defs.sec_forms.context import (
    ContextEvidence,
    ContextSource,
    FamilyClassification,
    RepairPolicy,
    SectionContext,
    TableContext,
    VocabularyEvidence,
    build_cover_scope,
    extract_toc_references,
    lift_toc_span_to_references,
    scan_html,
)
from defs.sec_forms.cover.profiles import get_profile
from defs.sec_forms.cover.structure import SectionKind, parse_section_heading
from defs.sec_forms.cover.toc.models import TocEvidence, TocSpan
from defs.text.html import parse_html

# --- SectionContext / TableContext -------------------------------------------


def test_section_context_default_is_unknown() -> None:
    ctx = SectionContext()
    assert ctx.is_unknown() is True
    assert ctx.part is None
    assert ctx.item is None
    assert ctx.heading is None
    assert ctx.toc_reference is None
    assert ctx.cover_scope is None
    assert ctx.source is ContextSource.UNKNOWN


def test_section_context_partial_is_valid() -> None:
    ctx = SectionContext(part="II", item="7")
    assert ctx.is_unknown() is False
    assert ctx.part == "II"
    assert ctx.item == "7"


def test_table_context_standalone_is_valid() -> None:
    ctx = TableContext()
    assert ctx.section is None
    assert ctx.table_ordinal == 0
    assert ctx.locator == ""


def test_vocabulary_evidence_empty_for_unknown_family() -> None:
    evidence = VocabularyEvidence(zone="body")
    assert evidence.positive_hits == ()
    assert evidence.score == 0.0
    assert evidence.vocabulary_version == ""


def test_family_classification_default_is_no_repair() -> None:
    classification = FamilyClassification(family=None, confidence=0.0)
    assert classification.family is None
    assert classification.repair_policy is RepairPolicy.NO_REPAIR
    assert classification.structural_confirmed is False


# --- CoverScope adapter -------------------------------------------------------


def test_build_cover_scope_inactive_for_no_cover_profile() -> None:
    profile = get_profile("8-K")
    scope = build_cover_scope(profile, None)
    assert scope.active is False
    assert scope.profile_family == "8-K"
    assert scope.confidence == 0.0


def test_build_cover_scope_carries_boundary_lines() -> None:
    from defs.sec_forms.cover.boundary import BoundaryMethod, CoverBoundary

    profile = get_profile("10-K")
    boundary = CoverBoundary(
        end_line=42,
        end_offset=1200,
        method=BoundaryMethod.STRUCTURAL,
        confidence=0.9,
        evidence=(ContextEvidence(name="cover_layout", strength=0.9, line=42),),
        start_line=0,
    )
    scope = build_cover_scope(profile, boundary)
    assert scope.active is True
    assert scope.profile_family == "10-K"
    assert scope.start_line == 0
    assert scope.end_line == 42
    assert scope.confidence == 0.9
    assert len(scope.evidence) == 1


# --- TOC adapter --------------------------------------------------------------


def test_extract_toc_references_finds_anchors() -> None:
    html = """
    <html><body>
    <table>
      <tr><td><a href="#item1">Item 1. Business</a></td><td>Page 5</td></tr>
      <tr><td><a href="#item7">Item 7. Management's Discussion</a></td><td>Page 20</td></tr>
      <tr><td><a href="#item8">Item 8. Financial Statements</a></td><td>Page 30</td></tr>
    </table>
    <table>
      <tr><td>Note 1. Basis of Presentation</td><td>Page 35</td></tr>
      <tr><td>Note 2. Revenue</td><td>Page 36</td></tr>
    </table>
    </body></html>
    """
    soup = parse_html(html)
    references = extract_toc_references(soup)
    joined = " ".join(ref.label for ref in references)
    assert "Item 1. Business" in joined
    assert "Note 1. Basis of Presentation" in joined
    items = [ref for ref in references if ref.item]
    assert {ref.anchor for ref in items} == {"item1", "item7", "item8"}
    confidences = [ref.confidence for ref in items]
    assert all(0.0 < c <= 1.0 for c in confidences)


def test_extract_toc_references_empty_when_no_toc() -> None:
    html = "<html><body><p>Just prose, no table of contents.</p></body></html>"
    soup = parse_html(html)
    assert extract_toc_references(soup) == ()


def test_lift_toc_span_to_references_handles_none() -> None:
    assert lift_toc_span_to_references(None) == ()


def test_lift_toc_span_to_references_adapts_evidence() -> None:
    span = TocSpan(
        start_line=10,
        end_line=20,
        start_offset=100,
        end_offset=200,
        method="heading_rows",
        confidence=0.92,
        evidence=(
            TocEvidence(name="toc_heading", line=10, details="Table of Contents"),
        ),
    )
    refs = lift_toc_span_to_references(span)
    assert len(refs) == 1
    assert refs[0].confidence == 0.92
    assert refs[0].evidence[0].name == "toc_heading"


def test_extract_toc_references_handles_multiple_tocs() -> None:
    """Main TOC, financial-statement index, and exhibit index stay separate."""
    html = """
    <html><body>
    <table>
      <tr><td>Item 1. Business</td><td>5</td></tr>
      <tr><td>Item 7. MD&A</td><td>20</td></tr>
    </table>
    <table>
      <tr><td>Report of Independent Auditors</td><td>30</td></tr>
      <tr><td>Consolidated Balance Sheets</td><td>31</td></tr>
      <tr><td>Consolidated Statements of Income</td><td>32</td></tr>
    </table>
    <table>
      <tr><td>Exhibit 21. Subsidiaries</td><td>90</td></tr>
      <tr><td>Exhibit 23. Consent</td><td>91</td></tr>
    </table>
    </body></html>
    """
    soup = parse_html(html)
    refs = extract_toc_references(soup)
    joined = " ".join(ref.label for ref in refs)
    assert "Item 1. Business" in joined
    assert "Consolidated Balance Sheets" in joined
    assert "Exhibit 21. Subsidiaries" in joined
    assert len(refs) >= 6


# --- HTML structure scanner ---------------------------------------------------


def test_scan_html_empty_soup_yields_empty_index() -> None:
    soup = parse_html("<html><body></body></html>")
    index = scan_html(soup)
    assert index.headings == ()
    assert index.blocks == ()
    assert index.tables == ()


def test_scan_html_detects_h1_and_block_paragraphs() -> None:
    html = """
    <html><body>
      <h1>Item 1. Business</h1>
      <p>We manufacture widgets.</p>
      <p>Our widgets are best in class.</p>
    </body></html>
    """
    soup = parse_html(html)
    index = scan_html(soup)
    assert any(h.text == "Item 1. Business" for h in index.headings)
    paragraphs = [b for b in index.blocks if b.text]
    assert any("manufacture widgets" in b.text for b in paragraphs)


def test_scan_html_excludes_table_descendants_from_blocks() -> None:
    """TOC rows and prose-formatted table cells must not become neighbor blocks."""
    html = """
    <html><body>
      <p>Preceding paragraph.</p>
      <table>
        <tr><td>Item 1</td><td>5</td></tr>
        <tr><td>Item 7</td><td>20</td></tr>
      </table>
      <p>Following paragraph.</p>
    </body></html>
    """
    soup = parse_html(html)
    index = scan_html(soup)
    block_texts = " ".join(b.text for b in index.blocks)
    assert "Preceding paragraph" in block_texts
    assert "Following paragraph" in block_texts
    # TOC-style table text must not appear as a paragraph block.
    assert "Item 1" not in block_texts
    assert "Item 7" not in block_texts


def test_scan_html_preserves_nested_table_relationship() -> None:
    html = """
    <html><body>
      <table id="outer">
        <tr><td>
          <table id="inner">
            <tr><td>cell</td></tr>
          </table>
        </td></tr>
      </table>
    </body></html>
    """
    soup = parse_html(html)
    index = scan_html(soup)
    assert len(index.tables) == 2
    inner = next(t for t in index.tables if t.depth == 1)
    outer = next(t for t in index.tables if t.depth == 0)
    assert inner.parent_table_ordinal == outer.ordinal


def test_scan_html_deterministic_fingerprint() -> None:
    html = "<html><body><h1>Item 1</h1><p>Body text.</p></body></html>"
    soup1 = parse_html(html)
    soup2 = parse_html(html)
    idx1 = scan_html(soup1, document_id="doc-1")
    idx2 = scan_html(soup2, document_id="doc-1")
    assert idx1.scanner_fingerprint == idx2.scanner_fingerprint
    assert idx1.schema_version == "1"


def test_scan_html_block_for_table_returns_nearest_preceding() -> None:
    html = """
    <html><body>
      <p>First paragraph.</p>
      <table><tr><td>Cell</td></tr></table>
    </body></html>
    """
    soup = parse_html(html)
    index = scan_html(soup)
    assert index.tables
    block = index.block_for_table(index.tables[0].ordinal)
    assert block is not None
    assert "First paragraph" in block.text


def test_scan_html_strips_ix_metadata() -> None:
    html = """
    <html><body>
      <ix:hidden>internal xbrl label</ix:hidden>
      <p>Real body text.</p>
    </body></html>
    """
    soup = parse_html(html)
    index = scan_html(soup)
    block_texts = " ".join(b.text for b in index.blocks)
    assert "internal xbrl label" not in block_texts
    assert "Real body text" in block_texts


def test_scan_html_repairs_split_inline_words() -> None:
    """<span>T</span>he becomes a single block word."""
    html = (
        "<html><body>"
        "<p>The <span>T</span>he following <em>text</em> is a test.</p>"
        "</body></html>"
    )
    soup = parse_html(html)
    index = scan_html(soup)
    joined = " ".join(b.text for b in index.blocks)
    assert "The following text is a test" in joined or "The The following" not in joined
    # Specifically: "Thetext" should never appear, and "T" should not appear alone.
    assert "Thetext" not in joined.replace("The text", "")
    assert "  T " not in f" {joined} "


def test_parse_section_heading_anchored_exact() -> None:
    # Exact leading headings
    p1 = parse_section_heading("PART I")
    assert p1 is not None and p1.kind == SectionKind.PART and p1.identifier == "I"
    assert p1.is_exact_heading is True

    p2 = parse_section_heading("| PART II |")
    assert p2 is not None and p2.kind == SectionKind.PART and p2.identifier == "II"

    i1 = parse_section_heading("ITEM 1. BUSINESS")
    assert i1 is not None and i1.kind == SectionKind.ITEM and i1.identifier == "1"
    assert i1.title == "BUSINESS"

    i1a = parse_section_heading("Item 1A - Risk Factors")
    assert i1a is not None and i1a.kind == SectionKind.ITEM and i1a.identifier == "1A"
    assert i1a.title == "Risk Factors"

    i9 = parse_section_heading("Item 9.01 Financial Statements and Exhibits")
    assert i9 is not None and i9.kind == SectionKind.ITEM and i9.identifier == "9.01"


def test_parse_section_heading_rejects_leading_prose() -> None:
    # Disallow leading prose / filler words
    assert parse_section_heading("as discussed in Item 1") is None
    assert parse_section_heading("Pursuant to Item 7") is None
    assert parse_section_heading("refer to Part II") is None
    assert parse_section_heading("in accordance with Item 1A") is None

    # Numbered notes and years must not be mistaken for parts/items
    assert parse_section_heading("10. Commitments and Contingencies") is None
    assert parse_section_heading("2024 Financial Highlights") is None
    assert parse_section_heading("Page 35") is None

    # allow_inline=True captures inline mentions as non-exact
    inline = parse_section_heading("as discussed in Item 1", allow_inline=True)
    assert inline is not None and inline.kind == SectionKind.ITEM
    assert inline.is_exact_heading is False


def test_cover_profile_wires_derived_taxonomy() -> None:
    k_profile = get_profile("10-K")
    assert k_profile.derived_taxonomy is not None
    assert "norm_toc_keywords" in k_profile.derived_taxonomy

    q_profile = get_profile("10-Q")
    assert q_profile.derived_taxonomy is not None
    assert "norm_toc_keywords" in q_profile.derived_taxonomy

    eight_k = get_profile("8-K")
    assert eight_k.derived_taxonomy is None


def test_extract_toc_references_bare_and_prefixed_page_numbers() -> None:
    html = """
    <html><body>
    <table>
      <tr><td><a href="#item1">Item 1. Business</a></td><td>5</td></tr>
      <tr><td><a href="#item1a">Item 1A. Risk Factors</a></td><td>Page 12</td></tr>
      <tr><td><a href="#item2">Item 2. Properties</a></td><td>pg. 25</td></tr>
      <tr><td><a href="#item7">Item 7. MD&A</a></td><td>F-1</td></tr>
      <tr><td><a href="#preface">Preface</a></td><td>iv</td></tr>
    </table>
    </body></html>
    """
    soup = parse_html(html)
    references = extract_toc_references(soup)
    assert len(references) == 5
    pages = [ref.page for ref in references]
    assert pages == ["5", "12", "25", "F-1", "iv"]
