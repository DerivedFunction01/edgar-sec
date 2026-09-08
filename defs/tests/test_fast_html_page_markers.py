"""Unit and contract tests for fast HTML break-to-text page marker pipeline."""

from __future__ import annotations

from defs.sec_forms.page_markers.ascii.candidates import classify_candidate
from defs.sec_forms.page_markers.fast_html import (
    analyze_fast_html_page_markers,
    apply_fast_html_page_policy,
    convert_html_to_break_text,
)
from defs.sec_forms.page_markers.models import PageArtifactPolicy, PageMarkerKind
from defs.sec_forms.page_markers.orchestrator import (
    apply_html_policy,
)


def test_apple_pipe_header_candidate_classification() -> None:
    line = "Apple Inc. | 2025 Form 10-K | 1"
    cand = classify_candidate(line, 0, 0)
    assert cand is not None
    assert cand.value == 1
    assert cand.family == PageMarkerKind.TRAILING_NUMBER
    assert cand.text == line


def test_convert_html_to_break_text_with_breaks_and_tables() -> None:
    html = """
    <html>
    <body>
        <h1>Cover Header</h1>
        <p>Some initial text.</p>
        <hr>
        <p>BJ'S RESTAURANTS, INC.</p>
        <table border="1">
            <tr><th>Metric</th><th>Value</th></tr>
            <tr><td>Revenues</td><td>$100,000</td></tr>
        </table>
        <p>1</p>
        <div style="page-break-before: always;">
            <p>BJ'S RESTAURANTS, INC.</p>
            <p>Page body paragraph on second page.</p>
            <p>2</p>
        </div>
    </body>
    </html>
    """
    text = convert_html_to_break_text(html)
    assert "<PAGE>" in text
    assert text.count("<PAGE>") >= 2
    assert "COVER HEADER" in text or "Cover Header" in text
    assert "BJ'S RESTAURANTS, INC." in text
    assert "Revenues" in text


def test_fast_html_analysis_on_synthetic_pages() -> None:
    html = """
    <html>
    <body>
        <p>Cover paragraph</p>
        <hr>
        <p>ACME CORPORATION</p>
        <p>Section 1 body content...</p>
        <p>1</p>
        <hr>
        <p>ACME CORPORATION</p>
        <p>Section 2 body content...</p>
        <p>2</p>
        <hr>
        <p>ACME CORPORATION</p>
        <p>Section 3 body content...</p>
        <p>3</p>
    </body>
    </html>
    """
    analysis = analyze_fast_html_page_markers(html)
    page_numbers = [
        m.page_number for m in analysis.markers if m.page_number is not None
    ]
    assert page_numbers == [1, 2, 3]
    assert len(analysis.page_number_runs) >= 1
    assert [c.value for c in analysis.page_number_runs[0].candidates] == [1, 2, 3]


def test_apply_fast_html_page_policy_strip_and_annotate() -> None:
    html = """
    <html>
    <body>
        <p>Document Start</p>
        <hr>
        <p>CORP NAME</p>
        <p>First section body text...</p>
        <p>1</p>
        <hr>
        <p>CORP NAME</p>
        <p>Second section body text...</p>
        <p>2</p>
        <hr>
        <p>CORP NAME</p>
        <p>Third section body text...</p>
        <p>3</p>
    </body>
    </html>
    """
    # Test strip policy
    stripped_text, _, artifacts, _, _, _ = apply_fast_html_page_policy(
        html, policy=PageArtifactPolicy.STRIP
    )
    assert "First section body text" in stripped_text
    assert "Second section body text" in stripped_text
    assert "Third section body text" in stripped_text
    assert len(artifacts) >= 3

    # Test annotate policy
    annotated_text, _, ann_artifacts, _, _, _ = apply_fast_html_page_policy(
        html, policy=PageArtifactPolicy.ANNOTATE
    )
    assert "[[SEC:PAGE_NUMBER" in annotated_text or "[[SEC:PAGE_BREAK" in annotated_text
    assert len(ann_artifacts) >= 3


def test_orchestrator_routes_html_to_fast_html() -> None:
    html = """
    <html>
    <body>
        <p>Item 1</p>
        <hr>
        <p>Apple Inc. | 2025 Form 10-K | 1</p>
        <p>First section body text...</p>
        <hr>
        <p>Apple Inc. | 2025 Form 10-K | 2</p>
        <p>Second section body text...</p>
        <hr>
        <p>Apple Inc. | 2025 Form 10-K | 3</p>
        <p>Third section body text...</p>
    </body>
    </html>
    """
    analysis = analyze_fast_html_page_markers(html)
    page_numbers = [
        m.page_number for m in analysis.markers if m.page_number is not None
    ]
    assert page_numbers == [1, 2, 3]

    # Test apply_html_policy
    result_text, _, artifacts, _, _, _ = apply_html_policy(
        html, policy=PageArtifactPolicy.STRIP
    )
    assert "First section body text" in result_text
    assert "Second section body text" in result_text
    assert "Third section body text" in result_text
    assert len(artifacts) >= 3


def test_decompose_whitespace_only_lines() -> None:
    html = "<p>Line 1</p>\n\t\n  \t  \n<p>Line 2</p>"
    text = convert_html_to_break_text(html)
    assert text == "Line 1\n\nLine 2"
