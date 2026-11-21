"""Repeated tables: when a table is furniture and when it is content."""

from __future__ import annotations

from edgar_sec.engine.document.page_markers.detector import analyze_page_markers
from edgar_sec.engine.document.page_markers.policy import apply_page_markers
from tests.engine.document.page_markers.policy.policy_support import _paged


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
