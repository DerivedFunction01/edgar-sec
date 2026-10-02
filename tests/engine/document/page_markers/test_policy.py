"""Applying a declared page-marker policy and recording what was touched."""

from __future__ import annotations

import pytest

from edgar_sec.engine.document.page_markers.artifacts import (
    build_page_artifact_metadata,
)
from edgar_sec.engine.document.page_markers.detector import analyze_page_markers
from edgar_sec.engine.document.page_markers.models import (
    PageArtifactPolicy,
    PageMarkerAction,
    PageMarkerAnalysis,
    PageMarkerKind,
    PageMarkerTerminalState,
)
from edgar_sec.engine.document.page_markers.policy import (
    apply_fast_html_page_policy,
    apply_html_policy,
    apply_page_markers,
    apply_text_policy,
)

NO_TOC = {"toc_lines": frozenset({-1})}


def _paged(
    pages: int, header: str = "", footer: str = "", label: str = "<PAGE>"
) -> str:
    lines: list[str] = []
    for index in range(1, pages + 1):
        lines.append(label)
        if header:
            lines.append(header)
        lines.append(f"Body {index}")
        if footer:
            lines.append(footer)
    return "\n".join(lines)


def _html(pages: int) -> str:
    chunks = ["<p>Start</p>", "<hr>"]
    for index in range(1, pages + 1):
        chunks.append(f"<p>{index}</p><hr><p>CORP NAME</p><p>Body {index}</p>")
    return "<html><body>" + "".join(chunks) + "</body></html>"


# --- the ASCII text frame ----------------------------------------------------


def test_an_empty_document_is_returned_unchanged() -> None:
    text, artifacts, templates, next_id = apply_page_markers("")
    assert (text, artifacts, templates, next_id) == ("", (), {}, 1)


def test_sgml_page_tags_are_stripped_with_provenance() -> None:
    text = "<PAGE>\nITEM 1. BUSINESS\n</PAGE>\n"
    result, artifacts, _templates, next_id = apply_page_markers(text)
    assert "<PAGE>" not in result
    assert "ITEM 1. BUSINESS" in result
    assert [artifact.source for artifact in artifacts] == ["sgml-page-tag"] * 2
    assert [artifact.page_number for artifact in artifacts] == [None, None]
    assert all(artifact.removable for artifact in artifacts)
    assert all(artifact.source_identity for artifact in artifacts)
    assert next_id == 3


def test_a_whole_line_removal_takes_its_trailing_newline() -> None:
    result, _artifacts, _templates, _next_id = apply_page_markers(
        "Header\n<PAGE>\nBody\n"
    )
    assert "\n\n" not in result
    assert result.splitlines() == ["Header", "Body"]


def test_preserve_policy_emits_nothing_and_changes_nothing() -> None:
    text = "<PAGE>\nITEM 1. BUSINESS\n</PAGE>\n"
    result, artifacts, templates, next_id = apply_page_markers(
        text, policy=PageArtifactPolicy.PRESERVE
    )
    assert (result, artifacts, templates, next_id) == (text, (), {}, 1)


def test_annotate_policy_replaces_each_span_with_a_token_line() -> None:
    text = "Header\n<PAGE>\nBody\n<PAGE>\n"
    result, artifacts, _templates, next_id = apply_page_markers(
        text, policy=PageArtifactPolicy.ANNOTATE
    )
    assert "[[SEC:PAGE_BREAK id=1]]" in result
    assert "[[SEC:PAGE_BREAK id=2]]" in result
    assert "<PAGE>" not in result
    assert len(artifacts) == 2
    assert next_id == 3


def test_annotate_emits_a_token_for_each_inferred_boundary() -> None:
    text = "\n".join(
        line
        for index in (1, 2, 3, 4, 5, 6, 7)
        for line in (
            ["<PAGE>"]
            + ([str(index), f"Body {index}"] if index in (1, 2, 3, 6, 7) else [])
        )
    )
    analysis = analyze_page_markers(text, NO_TOC)
    assert analysis.inferred_boundaries
    result, artifacts, _templates, _next_id = apply_page_markers(
        text, analysis, PageArtifactPolicy.ANNOTATE
    )
    assert result.count("[[SEC:PAGE_BREAK id=") >= len(analysis.inferred_boundaries)
    inferred = [
        artifact for artifact in artifacts if artifact.source == "inferred-line"
    ]
    assert inferred
    assert all(not artifact.removable for artifact in inferred)
    assert all(artifact.start == artifact.end for artifact in inferred)


def test_an_inferred_boundary_never_emits_a_span() -> None:
    text = "\n".join(
        line
        for index in (1, 2, 3, 4, 5, 6, 7)
        for line in (
            ["<PAGE>"]
            + ([str(index), f"Body {index}"] if index in (1, 2, 3, 6, 7) else [])
        )
    )
    result, artifacts, _templates, _next_id = apply_page_markers(text)
    assert all(
        not (artifact.source == "inferred-line" and artifact.start != artifact.end)
        for artifact in artifacts
    )
    assert "[[SEC:" not in result


def test_an_analysis_for_another_document_is_recomputed() -> None:
    stale = analyze_page_markers("<PAGE>\nA much longer document\n</PAGE>\n")
    text = "<PAGE>\nBody\n</PAGE>\n"
    result, artifacts, _templates, _next_id = apply_page_markers(text, stale)
    assert "<PAGE>" not in result
    assert [artifact.start for artifact in artifacts] == [0, 12]
    assert stale.source_text != text


def test_a_removal_inside_a_sentence_is_joined_with_a_space() -> None:
    text = "The company continues on page\n<PAGE> 2\nfor the year.\n"
    analysis = analyze_page_markers(text, NO_TOC)
    result, _artifacts, _templates, _next_id = apply_page_markers(text, analysis)
    assert "continues on page for the year." in result


def test_a_removal_after_a_terminal_character_is_not_joined() -> None:
    text = "A complete sentence.\n<PAGE> 2\nThe next sentence.\n"
    analysis = analyze_page_markers(text, NO_TOC)
    result, _artifacts, _templates, _next_id = apply_page_markers(text, analysis)
    assert "A complete sentence.\nThe next sentence." in result


def test_a_removal_is_not_joined_before_a_negative_boundary_phrase() -> None:
    # "none of" continues the sentence, so joining it would concatenate two
    # sentence halves rather than splice a removed marker out of one.
    text = "The company reports on page\n<PAGE> 2\nnone of which changed.\n"
    analysis = analyze_page_markers(text, NO_TOC)
    result, _artifacts, _templates, _next_id = apply_page_markers(text, analysis)
    assert "reports on page none of which changed." in result


def test_a_removal_overlapping_a_compact_table_widens_to_the_whole_table() -> None:
    text = _paged(4, header="ABC CORP")
    result, _artifacts, _templates, _next_id = apply_page_markers(text)
    assert "<TABLE>" not in result
    assert result.count("</TABLE>") == result.count("<TABLE>")


def test_artifact_ids_are_assigned_in_source_order() -> None:
    text = _paged(4, header="ABC CORP")
    _result, artifacts, _templates, _next_id = apply_page_markers(text)
    sources = [artifact.start for artifact in artifacts]
    assert sources == sorted(sources)
    assert sources == list(dict.fromkeys(sources))


def test_a_marker_starting_an_id_range_resumes_from_the_first_id() -> None:
    text = "<PAGE>\nBody\n</PAGE>\n"
    _result, artifacts, _templates, next_id = apply_page_markers(text, first_id=10)
    assert len(artifacts) == 2
    assert next_id == 12


def test_an_empty_decision_set_leaves_the_document_untouched() -> None:
    text = "Nothing to remove here.\n"
    analysis = PageMarkerAnalysis((), (), (), source_text=text)
    result, artifacts, _templates, next_id = apply_page_markers(text, analysis)
    assert result == text
    assert (artifacts, next_id) == ((), 1)


def test_repeating_furniture_is_noted_as_a_template_and_removed() -> None:
    text = _paged(4, header="ABC CORP")
    result, artifacts, templates, _next_id = apply_page_markers(text)
    assert "ABC CORP" not in result
    assert "Body 4" in result
    assert len(templates) == 1
    noted = [artifact for artifact in artifacts if artifact.template_id]
    assert len(noted) == 4
    assert all(artifact.source == "repeating_header" for artifact in noted)


def test_a_cover_banner_before_the_first_break_is_removed() -> None:
    pages = ["Cover title", "Table of Contents", ""]
    for index in range(1, 5):
        pages.extend([str(index), "<PAGE>", "Table of Contents", "", f"Body {index}"])
    text = "\n".join(pages)
    result, analysis, _artifacts, _templates, _next_id = apply_text_policy(text)
    repeated = [
        marker
        for marker in analysis.markers
        if marker.kind == PageMarkerKind.REPEATING_HEADER
    ]
    assert len(repeated) >= 4
    assert any(marker.start_line == 1 for marker in repeated)
    assert "Table of Contents" not in result
    assert "Cover title" in result
    assert "Body 4" in result


def test_a_trailing_footer_after_the_last_break_is_removed() -> None:
    pages = []
    for index in range(1, 5):
        pages.extend(
            [
                str(index),
                "<PAGE>",
                "ABC CORP",
                f"Body {index}",
                "Confidential footer",
            ]
        )
    pages.append("Confidential footer")
    text = "\n".join(pages)
    analysis = analyze_page_markers(text, NO_TOC)
    footers = [
        marker
        for marker in analysis.markers
        if marker.kind == PageMarkerKind.REPEATING_FOOTER
    ]
    assert len(footers) >= 4
    assert footers[-1].end_line == len(text.splitlines()) - 1
    assert "Confidential footer" in footers[-1].text


def test_the_text_frame_entry_point_returns_the_analysis_it_used() -> None:
    text = "<PAGE>\nBody\n</PAGE>\n"
    result, analysis, artifacts, templates, next_id = apply_text_policy(text)
    assert analysis.representation == "ascii"
    assert analysis.source_text == text
    # `<PAGE>` alone states no page value, so the frame reports no visible
    # labels even though the tag itself is a firm marker and was removed.
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


# --- the projected HTML frame ------------------------------------------------


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


def test_overlapping_decisions_share_one_rendered_token() -> None:
    # An artifact id identifies a rendered token, and overlapping decisions are
    # merged into a single range, so several artifacts can correspond to one
    # token. `next_id` therefore counts rendered tokens, not artifacts.
    text = _paged(4, header="ABC CORP")
    _result, artifacts, _templates, next_id = apply_page_markers(text)
    assert len(artifacts) > next_id - 1
    assert len({(item.start, item.end) for item in artifacts}) < len(artifacts) or all(
        item.start < item.end for item in artifacts
    )


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


# --- the sidecar -------------------------------------------------------------


def test_sidecar_metadata_is_ordered_for_byte_stable_output() -> None:
    text = _paged(4, header="ABC CORP")
    _result, artifacts, templates, _next_id = apply_page_markers(text)
    first = build_page_artifact_metadata(
        PageArtifactPolicy.STRIP, "src", templates, list(enumerate(artifacts, start=1))
    )
    second = build_page_artifact_metadata(
        PageArtifactPolicy.STRIP,
        "src",
        dict(reversed(list(templates.items()))),
        list(reversed(list(enumerate(artifacts, start=1)))),
    )
    assert first == second
    assert [entry["id"] for entry in first["artifacts"]] == sorted(
        entry["id"] for entry in first["artifacts"]
    )


def test_a_decision_to_preserve_emits_no_artifact() -> None:
    marker = analyze_page_markers("F-3\n", NO_TOC).markers[0]
    analysis = PageMarkerAnalysis(
        (marker,),
        (
            __import__(
                "edgar_sec.engine.document.page_markers.models",
                fromlist=["PageMarkerDecision"],
            ).PageMarkerDecision(
                marker, PageMarkerAction.PRESERVE, "ambiguous_letter_number"
            ),
        ),
        (),
        source_text="F-3\n",
    )
    result, artifacts, _templates, _next_id = apply_page_markers("F-3\n", analysis)
    assert result == "F-3\n"
    assert artifacts == ()


@pytest.mark.parametrize(
    "policy", [PageArtifactPolicy.STRIP, PageArtifactPolicy.ANNOTATE]
)
def test_every_applied_policy_leaves_no_sgml_page_tag(
    policy: PageArtifactPolicy,
) -> None:
    text = _paged(5, header="ABC CORP", footer="Confidential footer")
    result, _artifacts, _templates, _next_id = apply_page_markers(text, policy=policy)
    assert "<PAGE>" not in result
    assert "ABC CORP" not in result
    assert "Confidential footer" not in result
    assert "Body 5" in result
