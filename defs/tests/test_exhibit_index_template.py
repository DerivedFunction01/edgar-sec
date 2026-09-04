"""Unit tests for Item 15/16 Exhibit Index template and multi-column alignment."""

from __future__ import annotations

from defs.tables.templates.exhibit_index import exhibit_index_template


def test_multi_column_exhibit_index_alignment() -> None:
    source_grid = [
        ["Incorporated by Reference"],
        [
            "Exhibit Number",
            "Exhibit Description",
            "Filed Herewith",
            "Form",
            "Period Ending",
            "Exhibit",
            "Filing Date",
        ],
        [
            "4.21",
            "First Supplemental Indenture",
            "8-K",
            "4.11",
            "11/6/2023",
        ],
        [
            "4.26",
            "Description of Securities",
            "10-K",
            "6/30/2024",
            "4.26",
            "7/30/2024",
        ],
        [
            "10.7",
            "Officers' Indemnification Trust Agreement",
            "X",
        ],
    ]

    rendered = exhibit_index_template(source_grid)
    assert rendered is not None
    assert "<TABLE>" in rendered
    assert "Exhibit Number" in rendered
    assert "Exhibit Description" in rendered
    assert "Filed Herewith" in rendered
    assert "Period Ending" in rendered
    assert "4.21" in rendered
    assert "8-K" in rendered
    assert "4.11" in rendered
    assert "11/6/2023" in rendered
    assert "6/30/2024" in rendered
    assert "X" in rendered


def test_compact_two_column_exhibit_index() -> None:
    source_grid = [
        ["Exhibit", "Description"],
        ["3.1", "Articles of Incorporation"],
        ["", "as amended to date."],
        ["3.2", "Bylaws"],
        ["3.3", "Certificate of Designation"],
    ]

    rendered = exhibit_index_template(source_grid)
    assert rendered is not None
    assert "<TABLE>" in rendered
    assert "3.1" in rendered
    assert "Articles of Incorporation" in rendered
    assert "as amended to date." in rendered


def test_non_exhibit_table_returns_none() -> None:
    source_grid = [
        ["Year", "Revenue", "Net Income"],
        ["2025", "$100", "$20"],
        ["2024", "$80", "$15"],
    ]
    assert exhibit_index_template(source_grid) is None
