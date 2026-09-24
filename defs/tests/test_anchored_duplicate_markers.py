from __future__ import annotations

from defs.sec_forms.page_markers import analyze_page_markers, strip_page_markers
from defs.sec_forms.page_markers.models import PageMarkerAction


def test_anchored_duplicate_page_numbers_stripped() -> None:
    # Construct a document where pages 1..5 appear, followed by a duplicate page 4 and 5,
    # then continuing 6..8. All are anchored to <PAGE>.
    doc_lines = [
        "Header prose for doc",
        "First section content here",
        "                                       1",
        "<PAGE>",
        "Second section content here",
        "                                       2",
        "<PAGE>",
        "Third section content here",
        "                                       3",
        "<PAGE>",
        "Fourth section first occurrence content",
        "                                       4",
        "<PAGE>",
        "Fifth section first occurrence content",
        "                                       5",
        "<PAGE>",
        "Restarted section begins",
        "Fourth section second occurrence content",
        "                                       4",
        "<PAGE>",
        "Fifth section second occurrence content",
        "                                       5",
        "<PAGE>",
        "Sixth section content",
        "                                       6",
        "<PAGE>",
        "Seventh section content",
        "                                       7",
        "<PAGE>",
        "Final content line",
    ]
    text = "\n".join(doc_lines)

    analysis = analyze_page_markers(text, representation="ascii")

    # Assert both occurrences of 4 and 5 were accepted as markers
    markers_for_4 = [m for m in analysis.markers if m.page_number == 4]
    markers_for_5 = [m for m in analysis.markers if m.page_number == 5]
    assert len(markers_for_4) == 2, (
        f"Expected 2 markers for page 4, got {len(markers_for_4)}"
    )
    assert len(markers_for_5) == 2, (
        f"Expected 2 markers for page 5, got {len(markers_for_5)}"
    )

    # Check decisions
    remove_decisions_for_4 = [
        d
        for d in analysis.decisions
        if d.marker.page_number == 4 and d.action == PageMarkerAction.REMOVE
    ]
    assert len(remove_decisions_for_4) == 2

    # Assert none of the 4s or 5s are marked unresolved (merged as single call)
    unresolved_4_or_5 = [u for u in analysis.unresolved if u.endswith((":4", ":5"))]
    assert len(unresolved_4_or_5) == 0, (
        f"Unexpected unresolved entries: {unresolved_4_or_5}"
    )

    # Assert strip_page_markers strips all of them
    stripped = strip_page_markers(text, analysis)
    assert "                                       4" not in stripped
    assert "                                       5" not in stripped
