"""Applying a declared page-marker policy and recording what was touched."""

from __future__ import annotations

import pytest

from edgar_sec.engine.document.page_markers.artifacts import (
    build_page_artifact_metadata,
)
from edgar_sec.engine.document.page_markers.detector import analyze_page_markers
from edgar_sec.engine.document.page_markers.models import (
    PageArtifactPolicy,
    PageMarker,
    PageMarkerAction,
    PageMarkerAnalysis,
    PageMarkerDecision,
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
    # "none of" continues the sentence, so joining it would concatenate two halves.
    text = "The company reports on page\n<PAGE> 2\nnone of which changed.\n"
    analysis = analyze_page_markers(text, NO_TOC)
    result, _artifacts, _templates, _next_id = apply_page_markers(text, analysis)
    assert "reports on page none of which changed." in result


def test_a_removal_overlapping_a_compact_table_widens_to_the_whole_table() -> None:
    text = _paged(4, header="ABC CORP")
    result, _artifacts, _templates, _next_id = apply_page_markers(text)
    assert "<TABLE>" not in result
    assert result.count("</TABLE>") == result.count("<TABLE>")


def test_a_compact_table_with_undecided_content_is_not_widened_into() -> None:
    # Only the page-of-total line carries a decision; the data lines beside
    # it are content, so the removal stays on the marker's own line.
    text = (
        "Intro\n"
        "<TABLE>\n"
        "Category A          100\n"
        "Page 1 of 2\n"
        "Category B          200\n"
        "</TABLE>\n"
        "Outro\n"
    )
    result, _artifacts, _templates, _next_id = apply_page_markers(text)
    assert "Category A          100" in result
    assert "Category B          200" in result
    assert "<TABLE>" in result
    assert "Page 1 of 2" not in result


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


def test_overlapping_decisions_share_one_rendered_token() -> None:
    # Overlapping decisions merge into one range, so `next_id` counts rendered tokens,
    # not artifacts.
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


def test_pipe_header_sequence_is_stripped_completely() -> None:
    lines = [
        line
        for index in range(1, 6)
        for line in (f"Body {index}", f"Company | Form 10-K | {index}", "<PAGE>")
    ]
    result, _artifacts, _templates, _next_id = apply_page_markers(
        "\n".join(lines) + "\n"
    )
    assert "Company | Form 10-K" not in result
    for index in range(1, 6):
        assert f"Body {index}" in result


def _paged_tables(pages: int, rows: list[str]) -> str:
    lines: list[str] = []
    for index in range(1, pages + 1):
        lines.append("<PAGE>")
        lines.append(f"Body {index}")
        lines.append("<TABLE>")
        lines.extend(row.format(index=index) for row in rows)
        lines.append("</TABLE>")
    return "\n".join(lines)


def test_distinct_tables_ending_pages_are_not_furniture() -> None:
    # Every page ends with a different seven-line financial table, so only the
    # closing tag repeats at the footer slot: the tables must survive whole.
    text = _paged_tables(
        6,
        [
            "Category {index}          100",
            "Other {index}               50",
            "Another {index}             25",
            "Subtotal {index}           175",
            "Total {index}              175",
        ],
    )
    analysis = analyze_page_markers(text, {"allow_table_furniture": True})
    result, _artifacts, _templates, _next_id = apply_page_markers(text, analysis)
    assert result.count("<TABLE>") == 6
    assert all(f"Total {index}" in result for index in range(1, 7))


def test_a_small_repeated_banner_table_is_removed_as_a_whole_block() -> None:
    text = _paged_tables(6, ["ACME CORP", "Annual Report"])
    analysis = analyze_page_markers(text, {"allow_table_furniture": True})
    result, _artifacts, _templates, _next_id = apply_page_markers(text, analysis)
    assert "<TABLE>" not in result
    assert "ACME CORP" not in result
    assert "Body 6" in result


def test_a_repeated_row_inside_a_large_table_is_not_removed() -> None:
    # The identical first row repeats across pages, but its table exceeds the
    # furniture size cap, so the catch is rejected rather than fragmented.
    text = _paged_tables(
        6,
        [
            "ACME CORP",
            "Category {index}          100",
            "Other {index}               50",
            "Another {index}             25",
            "Total {index}              175",
        ],
    )
    analysis = analyze_page_markers(text, {"allow_table_furniture": True})
    result, _artifacts, _templates, _next_id = apply_page_markers(text, analysis)
    assert result.count("ACME CORP") == 6
    assert result.count("<TABLE>") == 6


def test_apply_page_markers_strips_page_of_total_with_trailing_pages() -> None:
    text = "Header\nPage 1 of 4 Pages\nBody content\n"
    result, artifacts, _templates, _next_id = apply_page_markers(text)
    assert result == "Header\nBody content\n"
    assert len(artifacts) == 1
    assert artifacts[0].page_number == 1


def test_apply_page_markers_strips_inline_page_of_total_and_preserves_content() -> None:
    text = "CUSIP No. 28134710A       Page 2 of 4 Pages\nBody line\n"
    result, artifacts, _templates, _next_id = apply_page_markers(text)
    assert result == "CUSIP No. 28134710A\nBody line\n"
    assert len(artifacts) == 1
    assert artifacts[0].page_number == 2


def test_apply_page_markers_strips_continuation_line_completely() -> None:
    text = "First\n[Continued on following page(s)] Page 1 of 4 Pages\nSecond\n"
    result, artifacts, _templates, _next_id = apply_page_markers(text)
    assert result == "First\nSecond\n"
    assert len(artifacts) == 1


def test_a_repeated_signature_table_is_not_removed_as_a_block() -> None:
    # A signature line is cover content: its table is never furniture, however
    # often the signature block repeats across the filing's sections.
    text = _paged_tables(6, ["ACME CORP", "By:  /s/ JANE DOE"])
    analysis = analyze_page_markers(text, {"allow_table_furniture": True})
    result, _artifacts, _templates, _next_id = apply_page_markers(text, analysis)
    assert result.count("By:  /s/ JANE DOE") == 6
    assert result.count("<TABLE>") == 6


def test_a_repeated_cross_reference_table_is_not_removed_as_a_block() -> None:
    # Specimen: SC 13G cover table (0001011438-22-000070) — the instruction
    # lines are cross-references, so their table is content, not furniture.
    text = _paged_tables(
        6,
        [
            " *  SEE INSTRUCTIONS BEFORE FILLING OUT",
            "**  SEE ITEM 4.",
        ],
    )
    analysis = analyze_page_markers(text, {"allow_table_furniture": True})
    result, _artifacts, _templates, _next_id = apply_page_markers(text, analysis)
    assert result.count("SEE INSTRUCTIONS BEFORE FILLING OUT") == 6
    assert result.count("SEE ITEM 4.") == 6
    assert result.count("<TABLE>") == 6


def test_a_repeated_cross_reference_footer_survives_the_strip() -> None:
    # Specimen: F-1/A 0001002334-08-000136 defect_2 residual footer.
    text = _paged(6, footer="See Accountants\u2019 Audit Report")
    result, _artifacts, _templates, _next_id = apply_page_markers(text)
    assert result.count("See Accountants\u2019 Audit Report") == 6


def test_a_cross_reference_line_keeps_its_inline_page_of_total() -> None:
    text = "See page 2 of 9 pages\nBody line\n"
    result, artifacts, _templates, _next_id = apply_page_markers(text)
    assert result == text
    assert artifacts == ()


def test_a_table_line_decided_only_by_an_inline_marker_is_not_widened_into() -> None:
    # The inline page-of-total decides its own span only; the prose sharing
    # its line is content, so the table keeps everything but the marker.
    text = (
        "Intro\n"
        "<TABLE>\n"
        "Copyright Everest Reinsurance Company, 2009 Page 1 of 2\n"
        "</TABLE>\n"
        "Outro\n"
    )
    result, _artifacts, _templates, _next_id = apply_page_markers(text)
    assert "Copyright Everest Reinsurance Company, 2009" in result
    assert "<TABLE>" in result
    assert "Page 1 of 2" not in result


def _block_analysis(
    text: str, first_line: int, last_line: int, kind: str
) -> PageMarkerAnalysis:
    # One REMOVE decision whose marker covers whole lines first..last exactly.
    lines = text.split("\n")
    start = sum(len(line) + 1 for line in lines[:first_line])
    end = start + sum(len(line) + 1 for line in lines[first_line:last_line])
    end += len(lines[last_line])
    marker = PageMarker(
        start=start,
        end=end,
        text=text[start:end],
        kind=kind,
        start_line=first_line,
        end_line=last_line,
    )
    decision = PageMarkerDecision(
        marker=marker, action=PageMarkerAction.REMOVE, reason="test"
    )
    return PageMarkerAnalysis(
        markers=(marker,),
        decisions=(decision,),
        page_boundaries=(),
        source_text=text,
    )


def test_a_block_range_overlapping_a_table_is_unioned_not_replaced() -> None:
    # M1 reproduction (defect_2 census): the block decision starts before a
    # fully-decided compact table; replacing its range with the table's kept
    # the block's head line as silent under-removal — the sub='none' orphan
    # shape of the "Division of Corporation Finance" letterheads
    # (0000829224-21-000090). Union removes the head and the table together.
    text = (
        "Division of Corporation Finance\n"
        "<TABLE>\n"
        "ACME CORP\n"
        "</TABLE>\n"
        "Body text survives.\n"
    )
    analysis = _block_analysis(text, 0, 2, PageMarkerKind.REPEATING_FOOTER)
    result, _artifacts, _templates, _next_id = apply_page_markers(text, analysis)
    assert "Division of Corporation Finance" not in result
    assert "<TABLE>" not in result
    assert "Body text survives." in result


def test_a_marker_inside_a_compact_table_still_widens_to_the_whole_table() -> None:
    # Union semantics keep the atomic-table behaviour: a lone decided banner
    # line still takes the wrapper tags with it.
    text = "Intro\n<TABLE>\nACME CORP\n</TABLE>\nOutro\n"
    analysis = _block_analysis(text, 2, 2, PageMarkerKind.REPEATING_HEADER)
    result, _artifacts, _templates, _next_id = apply_page_markers(text, analysis)
    assert "<TABLE>" not in result
    assert "ACME CORP" not in result
    assert "Outro" in result


def test_a_fee_table_is_not_widened_into() -> None:
    # Specimen 0000080248-06-000005 (defect_4 D4-B): every fee line is
    # data-shaped (a bare percent), so the compact table is not furniture
    # however fully a block decision covers its lines.
    text = (
        "Intro\n"
        "<TABLE>\n"
        "Maximum sales load imposed on purchases (%)       None\n"
        "Maximum contingent deferred sales charge (%)      None\n"
        "Redemption Fees (%)                           None (1)\n"
        "</TABLE>\n"
        "Outro\n"
    )
    analysis = _block_analysis(text, 2, 4, PageMarkerKind.REPEATING_FOOTER)
    result, _artifacts, _templates, _next_id = apply_page_markers(text, analysis)
    assert "<TABLE>" in result
    assert "</TABLE>" in result
    assert "Outro" in result


def test_a_proxy_header_table_is_not_widened_into() -> None:
    # Specimen 0001213900-20-023787 (defect_4 D4-B): the meeting/record lines
    # carry guttered figures, so the header table is not widened over.
    text = (
        "Intro\n"
        "<TABLE>\n"
        "Ticker:          MMM         Security ID:   88579Y101\n"
        "Meeting Date:  MAY 12, 2020  Meeting Type:  Annual\n"
        "Record Date:   MAR 17, 2020\n"
        "</TABLE>\n"
        "Outro\n"
    )
    analysis = _block_analysis(text, 2, 4, PageMarkerKind.REPEATING_FOOTER)
    result, _artifacts, _templates, _next_id = apply_page_markers(text, analysis)
    assert "<TABLE>" in result
    assert "</TABLE>" in result


def test_a_rider_table_is_not_widened_into() -> None:
    # Specimen 0001072613-20-000194 (defect_4 D4-B): the rider row is a
    # guttered date/identifier row, so its table is not widened over.
    text = (
        "Intro\n"
        "<TABLE>\n"
        "Rider Effective Date     Bond Holder       Bond Number      Rider\n"
        "     11/4/2019        Barings BDC, Inc.  64-MGU-19-A48107     1\n"
        "</TABLE>\n"
        "Outro\n"
    )
    analysis = _block_analysis(text, 2, 3, PageMarkerKind.REPEATING_FOOTER)
    result, _artifacts, _templates, _next_id = apply_page_markers(text, analysis)
    assert "<TABLE>" in result
    assert "</TABLE>" in result


def test_a_date_table_is_not_widened_into() -> None:
    # A one-line date table (residual_other R-E shape) is a data table: its
    # only content line is a full date, so coverage alone cannot widen.
    text = "Intro\n<TABLE>\nAugust 31, 2020 (unaudited)\n</TABLE>\nOutro\n"
    analysis = _block_analysis(text, 2, 2, PageMarkerKind.REPEATING_HEADER)
    result, _artifacts, _templates, _next_id = apply_page_markers(text, analysis)
    assert "<TABLE>" in result
    assert "</TABLE>" in result


def test_a_year_header_table_is_not_widened_into() -> None:
    # Specimen shape 0001205613-04-000173 (residual_numeric R5): a year pair
    # is a column header, content by position, invisible to prose tests.
    text = "Intro\n<TABLE>\n2004 / 2003\n</TABLE>\nOutro\n"
    analysis = _block_analysis(text, 2, 2, PageMarkerKind.REPEATING_HEADER)
    result, _artifacts, _templates, _next_id = apply_page_markers(text, analysis)
    assert "<TABLE>" in result
    assert "</TABLE>" in result


def test_a_rule_lined_table_is_not_widened_into() -> None:
    # Specimen 0001539497-21-001637: rule lines are table borders, not
    # decided content lines, so they cannot satisfy full coverage.
    text = (
        "Intro\n"
        "<TABLE>\n"
        "-------------  --------------\n"
        "Annex A-1 ID#  Mortgage Loans\n"
        "-------------  --------------\n"
        "</TABLE>\n"
        "Outro\n"
    )
    analysis = _block_analysis(text, 2, 4, PageMarkerKind.REPEATING_FOOTER)
    result, _artifacts, _templates, _next_id = apply_page_markers(text, analysis)
    assert "<TABLE>" in result
    assert "</TABLE>" in result


def test_a_page_label_table_still_widens() -> None:
    # Furniture control for the data/date screens: a page-of-total line is
    # neither data-shaped nor a date line, so its table still widens whole.
    text = "Intro\n<TABLE>\nPage 1 of 2\n</TABLE>\nOutro\n"
    analysis = _block_analysis(text, 2, 2, PageMarkerKind.PAGE_NUMBER_OF_TOTAL)
    result, _artifacts, _templates, _next_id = apply_page_markers(text, analysis)
    assert "<TABLE>" not in result
    assert "Page 1 of 2" not in result
    assert "Outro" in result


def test_a_stacked_fragment_letterhead_survives_the_strip() -> None:
    # T. Rowe Price letterhead, fragmented one token per line: 0001193125-25-164006.
    pages = []
    for index in range(1, 9):
        pages.append(f"Schedule body {index} with portfolio data and commentary.")
        pages.append("<PAGE>")
        pages.append("T.\n\nROWE\n\nPRICE\n\nRetirement\n\n2030\n\nFund")
        pages.append(str(index + 1))
    text = "\n".join(pages)
    analysis = analyze_page_markers(
        text, {"allow_table_furniture": True}, representation="ascii"
    )
    stripped, _artifacts, _templates, _next = apply_page_markers(
        text, analysis, PageArtifactPolicy.STRIP
    )
    for fragment in ("T.", "ROWE", "PRICE", "Retirement", "Fund"):
        assert fragment in stripped


def test_a_running_head_and_page_number_strip_while_the_continuation_title_survives() -> (
    None
):
    # Glued bare number + running head around <PAGE>: 0001398344-19-019336.
    pages = []
    for index in range(1, 9):
        pages.append("SUMMIT GLOBAL INVESTMENTS")
        pages.append("Company Management (Unaudited) (continued)")
        pages.append(f"Management discussion body {index} in ordinary prose.")
        pages.append(f"{59 + index}")
        pages.append("<PAGE>")
    text = "\n".join(pages)
    analysis = analyze_page_markers(
        text, {"allow_table_furniture": True}, representation="ascii"
    )
    stripped, _artifacts, _templates, _next = apply_page_markers(
        text, analysis, PageArtifactPolicy.STRIP
    )
    # The continuation title is content; the running head, bare numbers, and
    # <PAGE> tags are furniture and still go (no keep-first for short heads).
    assert "Company Management (Unaudited) (continued)" in stripped
    assert "SUMMIT GLOBAL INVESTMENTS" not in stripped
    assert "<PAGE>" not in stripped
    assert "\n60\n" not in stripped


def _spanning_label_table(segments: list[list[str]]) -> str:
    lines = ["Intro", "<TABLE>"]
    for index, segment in enumerate(segments):
        if index:
            lines.append("<PAGE>")
        lines.extend(segment)
    lines.extend(["</TABLE>", "Outro"])
    return "\n".join(lines) + "\n"


def test_labels_inside_a_page_spanning_table_are_removed_with_the_table() -> None:
    # E5 shape: one table element spanning several pages, every appendix
    # label inside it; the whole furniture table widens away as one block.
    text = _spanning_label_table(
        [["------", "A - 1"], ["------", "A - 2"], ["------", "A - 3"]]
    )
    analysis = analyze_page_markers(text, {"allow_table_furniture": True})
    result, _artifacts, _templates, _next_id = apply_page_markers(text, analysis)
    assert "<TABLE>" not in result
    assert "------" not in result
    assert "A - 1" not in result
    assert "A - 3" not in result
    assert "Intro" in result
    assert "Outro" in result


def test_labels_in_non_spanning_tables_are_not_newly_widened() -> None:
    # Control (the S-4 specimen shape): each label in its own compact table
    # is removed alone, exactly as before; its husk is not the spanning case.
    text = (
        "Intro\n"
        "<TABLE>\n------\nA - 1\n</TABLE>\n<PAGE>\nBody 1\n"
        "<TABLE>\n------\nA - 2\n</TABLE>\n<PAGE>\nBody 2\n"
        "<TABLE>\n------\nA - 3\n</TABLE>\n<PAGE>\nBody 3\n"
    )
    analysis = analyze_page_markers(text, {"allow_table_furniture": True})
    result, _artifacts, _templates, _next_id = apply_page_markers(text, analysis)
    assert "A - 1" not in result
    assert result.count("<TABLE>") == 3
    assert result.count("------") == 3
    assert "Body 2" in result


def test_a_spanning_table_with_content_lines_is_not_widened() -> None:
    # A spanning table carrying undecided body rows is content: its labels
    # are removed alone and the table survives whole.
    text = _spanning_label_table(
        [
            ["------", "A - 1", "The merger agreement clause one applies."],
            ["------", "A - 2", "The merger agreement clause two applies."],
            ["------", "A - 3", "The merger agreement clause three applies."],
        ]
    )
    analysis = analyze_page_markers(text, {"allow_table_furniture": True})
    result, _artifacts, _templates, _next_id = apply_page_markers(text, analysis)
    assert "<TABLE>" in result
    assert "A - 1" not in result
    assert "clause two applies" in result


def test_a_spanning_table_without_a_letter_label_is_not_widened() -> None:
    # The spanning admission is scoped to appendix letter labels: bare page
    # numbers spanning a table keep the line-at-a-time behaviour.
    text = _spanning_label_table([["------", "1"], ["------", "2"], ["------", "3"]])
    analysis = analyze_page_markers(text, {"allow_table_furniture": True})
    result, _artifacts, _templates, _next_id = apply_page_markers(text, analysis)
    assert "<TABLE>" in result
    assert result.count("------") == 3
