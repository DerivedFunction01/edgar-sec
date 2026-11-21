"""Repeating furniture and letterheads under the strip policy."""

from __future__ import annotations

from edgar_sec.engine.document.page_markers.detector import analyze_page_markers
from edgar_sec.engine.document.page_markers.models import (
    PageArtifactPolicy,
    PageMarkerKind,
)
from edgar_sec.engine.document.page_markers.policy import (
    apply_page_markers,
    apply_text_policy,
)
from tests.engine.document.page_markers.policy.policy_support import NO_TOC, _paged


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
