from __future__ import annotations

from defs.text import normalize_final_text_whitespace, split_concatenated_bullets


def test_normalize_final_text_whitespace() -> None:
    text = "First  \nSecond\n\n\n\nThird\t\n"

    assert normalize_final_text_whitespace(text) == "First\nSecond\n\nThird\n"


def test_split_concatenated_bullets_semicolon_list() -> None:
    text = (
        "    o  to preserve capital; "
        "o  to maximize distributions; and "
        "o  to realize growth."
    )
    expected = (
        "    o  to preserve capital;\n"
        "o  to maximize distributions; and\n"
        "o  to realize growth."
    )
    assert split_concatenated_bullets(text) == expected


def test_split_concatenated_bullets_period_glyph_and_footnotes() -> None:
    text = "First item. • Second item. • Third item.\n* Note one. ** Note two."
    expected = "First item.\n• Second item.\n• Third item.\n* Note one.\n** Note two."
    assert split_concatenated_bullets(text) == expected


def test_split_concatenated_bullets_preserves_prose_and_officer_lines() -> None:
    text = (
        "• Residential mortgage loans – held-for-sale - FVO.\n"
        "• Maintain expenditures in the range of 2.0% - 2.5% of net sales.\n"
        "John Doe       54  •  Executive Vice President\n"
    )
    assert split_concatenated_bullets(text) == text


def test_split_concatenated_bullets_preserves_tagged_tables() -> None:
    text = "Item 1; • Item 2;\n<TABLE>\nCol 1; • Col 2;\n</TABLE>\nItem 3; • Item 4;\n"
    expected = (
        "Item 1;\n• Item 2;\n<TABLE>\nCol 1; • Col 2;\n</TABLE>\nItem 3;\n• Item 4;\n"
    )
    assert split_concatenated_bullets(text) == expected
