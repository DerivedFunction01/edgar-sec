"""Unit and contract tests for defs.sec_forms.cover.tables (clean_cover_tables)."""

from __future__ import annotations

from defs.sec_forms.cover.models import BoundaryMethod, CoverBoundary
from defs.sec_forms.cover.tables import clean_cover_tables
from defs.tables.ascii_html import TableGeometry, convert_html_table


def test_clean_cover_tables_unwraps_report_period_table() -> None:
    text = (
        "UNITED STATES SECURITIES AND EXCHANGE COMMISSION\n"
        "Washington, D.C. 20549\n"
        "<TABLE>\n"
        "[X] ANNUAL REPORT PURSUANT TO SECTION 13 OR 15(d) OF THE SECURITIES EXCHANGE ACT OF 1934\n"
        "</TABLE>\n"
        "<TABLE>\n"
        "[ ] TRANSITION REPORT PURSUANT TO SECTION 13 OR 15(d) OF THE ACT\n"
        "</TABLE>\n"
        "PART I\n"
        "ITEM 1. BUSINESS\n"
    )
    # boundary covers first 7 lines (before PART I)
    boundary = CoverBoundary(
        start_line=0,
        end_line=7,
        end_offset=200,
        method=BoundaryMethod.STRUCTURAL,
        confidence=1.0,
    )
    res1 = convert_html_table(
        "<table><tr><td>[X]</td><td>ANNUAL REPORT PURSUANT TO SECTION 13 OR 15(d) OF THE SECURITIES EXCHANGE ACT OF 1934</td></tr></table>"
    )
    res2 = convert_html_table(
        "<table><tr><td>[ ]</td><td>TRANSITION REPORT PURSUANT TO SECTION 13 OR 15(d) OF THE ACT</td></tr></table>"
    )
    geom1 = TableGeometry(table_index=0, render_result=res1)
    geom2 = TableGeometry(table_index=1, render_result=res2)

    cleaned, retained_geoms = clean_cover_tables(
        text,
        boundary,
        table_geometries=(geom1, geom2),
        enabled_cleaners=("report_period",),
    )

    assert "<TABLE>" not in cleaned
    assert "</TABLE>" not in cleaned
    assert "[X] ANNUAL REPORT PURSUANT TO SECTION 13" in cleaned
    assert "[ ] TRANSITION REPORT PURSUANT TO SECTION 13" in cleaned
    assert len(retained_geoms) == 0


def test_clean_cover_tables_preserves_tables_after_boundary() -> None:
    text = (
        "UNITED STATES SECURITIES AND EXCHANGE COMMISSION\n"
        "FORM 10-K\n"
        "<TABLE>\n"
        "[X] ANNUAL REPORT PURSUANT TO SECTION 13 OR 15(d) OF THE SECURITIES EXCHANGE ACT OF 1934\n"
        "</TABLE>\n"
        "PART IV\n"
        "ITEM 15. EXHIBITS\n"
        "<TABLE>\n"
        "Exhibit 10.1    Annual Report pursuant to Section 13 of the 1934 Act\n"
        "</TABLE>\n"
    )
    # Boundary ends at line 5 (after cover, before Part IV)
    boundary = CoverBoundary(
        start_line=0,
        end_line=5,
        end_offset=150,
        method=BoundaryMethod.STRUCTURAL,
        confidence=1.0,
    )
    res_cover = convert_html_table(
        "<table><tr><td>[X]</td><td>ANNUAL REPORT PURSUANT TO SECTION 13</td></tr></table>"
    )
    res_exhibit = convert_html_table(
        "<table><tr><td>Exhibit 10.1</td><td>Annual Report pursuant to Section 13 of the 1934 Act</td></tr></table>"
    )
    geom_cover = TableGeometry(table_index=0, render_result=res_cover)
    geom_exhibit = TableGeometry(table_index=1, render_result=res_exhibit)

    cleaned, retained_geoms = clean_cover_tables(
        text,
        boundary,
        table_geometries=(geom_cover, geom_exhibit),
        enabled_cleaners=("report_period",),
    )

    # Cover table should be unwrapped
    assert "[X] ANNUAL REPORT PURSUANT TO SECTION 13" in cleaned
    # Exhibit table MUST remain wrapped
    assert "<TABLE>\nExhibit 10.1" in cleaned
    assert len(retained_geoms) == 1
    assert retained_geoms[0] == geom_exhibit


def test_clean_cover_tables_noop_when_cleaner_disabled() -> None:
    text = (
        "<TABLE>\n"
        "[X] ANNUAL REPORT PURSUANT TO SECTION 13 OR 15(d) OF THE SECURITIES EXCHANGE ACT OF 1934\n"
        "</TABLE>\n"
    )
    boundary = CoverBoundary(
        start_line=0,
        end_line=5,
        end_offset=100,
        method=BoundaryMethod.STRUCTURAL,
        confidence=1.0,
    )
    res = convert_html_table(
        "<table><tr><td>[X]</td><td>ANNUAL REPORT</td></tr></table>"
    )
    geom = TableGeometry(table_index=0, render_result=res)

    cleaned, retained_geoms = clean_cover_tables(
        text,
        boundary,
        table_geometries=(geom,),
        enabled_cleaners=(),
    )

    assert cleaned == text
    assert retained_geoms == (geom,)


def test_clean_cover_tables_noop_when_no_boundary() -> None:
    text = (
        "<TABLE>\n"
        "[X] ANNUAL REPORT PURSUANT TO SECTION 13 OR 15(d) OF THE SECURITIES EXCHANGE ACT OF 1934\n"
        "</TABLE>\n"
    )
    boundary = CoverBoundary(
        start_line=None,
        end_line=None,
        end_offset=None,
        method=BoundaryMethod.DISABLED,
        confidence=0.0,
    )
    res = convert_html_table(
        "<table><tr><td>[X]</td><td>ANNUAL REPORT</td></tr></table>"
    )
    geom = TableGeometry(table_index=0, render_result=res)

    cleaned, retained_geoms = clean_cover_tables(
        text,
        boundary,
        table_geometries=(geom,),
        enabled_cleaners=("report_period",),
    )

    assert cleaned == text
    assert retained_geoms == (geom,)
