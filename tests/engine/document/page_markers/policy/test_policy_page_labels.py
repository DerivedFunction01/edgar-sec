"""Page-of-total and continuation markers in running text."""

from __future__ import annotations

from edgar_sec.engine.document.page_markers.policy import apply_page_markers


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
