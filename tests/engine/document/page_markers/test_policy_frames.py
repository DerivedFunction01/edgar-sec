"""The text and HTML frame entry points and their shared projection."""

from __future__ import annotations

from edgar_sec.engine.document.page_markers.detector import analyze_page_markers
from edgar_sec.engine.document.page_markers.models import (
    PageArtifactPolicy,
    PageMarkerAnalysis,
    PageMarkerKind,
    PageMarkerTerminalState,
)
from edgar_sec.engine.document.page_markers.policy import (
    apply_fast_html_page_policy,
    apply_html_policy,
    apply_text_policy,
)
from tests.engine.document.page_markers.policy_support import NO_TOC


def _html(pages: int) -> str:
    chunks = ["<p>Start</p>", "<hr>"]
    for index in range(1, pages + 1):
        chunks.append(f"<p>{index}</p><hr><p>CORP NAME</p><p>Body {index}</p>")
    return "<html><body>" + "".join(chunks) + "</body></html>"


def test_the_text_frame_entry_point_returns_the_analysis_it_used() -> None:
    text = "<PAGE>\nBody\n</PAGE>\n"
    result, analysis, artifacts, templates, next_id = apply_text_policy(text)
    assert analysis.representation == "ascii"
    assert analysis.source_text == text
    # `<PAGE>` alone states no page value, so no visible labels even though the tag was
    # a firm marker and was removed.
    assert analysis.terminal_state is PageMarkerTerminalState.NO_VISIBLE_LABELS
    assert artifacts
    assert templates == {}
    assert next_id == 3
    assert "<PAGE>" not in result


def test_the_text_frame_entry_point_keeps_the_given_analysis() -> None:
    text = "<PAGE>\nBody\n</PAGE>\n"
    analysis = analyze_page_markers(text, NO_TOC)
    _result, returned, _artifacts, _templates, _next_id = apply_text_policy(
        text, analysis
    )
    assert returned is analysis


def test_html_policy_uses_the_shared_projection_and_admits_table_furniture() -> None:
    html = _html(4)
    result, analysis, artifacts, _templates, next_id, _geometries = (
        apply_fast_html_page_policy(html)
    )
    assert analysis.representation == "ascii"
    assert "CORP NAME" not in result
    assert "Body 4" in result
    assert any(
        marker.kind == PageMarkerKind.REPEATING_HEADER for marker in analysis.markers
    )
    assert artifacts
    assert next_id >= 2


def test_html_policy_preserves_the_projection_s_table_geometry() -> None:
    html = (
        "<html><body><p>Lead</p>"
        "<table><tr><th>Metric</th><th>Value</th></tr>"
        "<tr><td>Revenues</td><td>$100,000</td></tr></table>"
        "<p>1</p></body></html>"
    )
    _result, _analysis, _artifacts, _templates, _next_id, geometries = (
        apply_fast_html_page_policy(html)
    )
    assert len(geometries) == 1
    assert len(geometries[0].rows) == 2


def test_html_annotate_emits_tokens_into_the_text_frame() -> None:
    html = _html(4)
    result, _analysis, artifacts, _templates, _next_id, _geometries = (
        apply_fast_html_page_policy(html, policy=PageArtifactPolicy.ANNOTATE)
    )
    assert "[[SEC:" in result
    assert artifacts


def test_an_analysis_declared_html_is_recomputed_in_the_text_frame() -> None:
    html = _html(3)
    stale = PageMarkerAnalysis(
        (), (), (), representation="html", source_text="some other html"
    )
    result, analysis, _artifacts, _templates, _next_id, _geometries = (
        apply_fast_html_page_policy(html, stale)
    )
    assert analysis.representation == "ascii"
    assert analysis.source_text == str(
        __import__(
            "edgar_sec.engine.document.html.breaks",
            fromlist=["render_html_to_break_text"],
        ).render_html_to_break_text(html)
    )
    assert "Body 3" in result


def test_an_empty_html_document_projects_to_an_empty_frame() -> None:
    result, analysis, artifacts, templates, next_id, geometries = (
        apply_fast_html_page_policy("")
    )
    assert result == ""
    assert analysis.markers == ()
    assert (artifacts, templates, next_id, geometries) == ((), {}, 1, ())


def test_the_html_facade_routes_to_the_same_projection() -> None:
    html = _html(3)
    direct = apply_fast_html_page_policy(html)
    facade = apply_html_policy(html)
    assert facade[0] == direct[0]
    assert facade[1] == direct[1]
    assert facade[2] == direct[2]
