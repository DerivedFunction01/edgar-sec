"""Detection and extraction for positioned-div filings."""

from __future__ import annotations

from edgar_sec.engine.document.html.breaks import insert_page_sentinels
from edgar_sec.engine.document.html.normalizer import decompose_html_structures
from edgar_sec.engine.document.html.positioned import (
    FlowLine,
    PositionedFragment,
    PositionedPage,
    TableBand,
    cluster_page_rows,
    detect_positioned_layout,
    extract_positioned_pages,
    layout_page,
    reconstruct_positioned_html,
)
from edgar_sec.engine.tables.ascii_html.converter import (
    convert_html_tables_to_ascii_with_metadata,
)
from tests.support import fixture_path

SPACER_DIV = '<div style="display:inline-block;width:6px">&#160;</div>'


def _synthetic_html() -> str:
    return fixture_path("document/positioned_sample.html").read_text(encoding="utf-8")


def _positioned_doc(fragment_count: int) -> str:
    fragments = "".join(
        f'<div style="position:absolute;left:{40 + (i % 4) * 100}px;'
        f'top:{50 + i * 17}px;">value {i}</div>'
        for i in range(fragment_count)
    )
    return (
        '<div style="position:relative;page-break-after:always;'
        f'width:816px;height:1056px;">{fragments}</div>'
    )


def test_detect_positioned_layout_on_synthetic_fixture() -> None:
    assert detect_positioned_layout(_synthetic_html())


def test_detect_rejects_table_based_document() -> None:
    html = "<table><tr><td>a</td></tr></table>" + _positioned_doc(30)
    assert not detect_positioned_layout(html)


def test_detect_rejects_decoration_only_absolutes() -> None:
    decorations = "".join(
        '<div style="position:absolute;right:0;bottom:0;">x</div>' for _ in range(40)
    )
    html = f"<div><p>ordinary prose filing body text here</p>{decorations}</div>"
    assert not detect_positioned_layout(html)


def test_detect_rejects_single_fragment_document() -> None:
    html = (
        "<p>annual report prose</p>"
        '<div style="position:absolute;left:10px;top:10px;">signed</div>'
    )
    assert not detect_positioned_layout(html)


def test_extract_groups_fragments_by_page() -> None:
    pages = extract_positioned_pages(_synthetic_html())
    assert len(pages) == 2
    assert len(pages[0].fragments) == 3
    assert len(pages[1].fragments) == 24


def test_extract_reads_coordinates_and_text() -> None:
    pages = extract_positioned_pages(_synthetic_html())
    net_sales = next(f for f in pages[1].fragments if f.text == "Net sales")
    assert (net_sales.top, net_sales.left) == (90.0, 48.0)
    value = next(f for f in pages[1].fragments if f.text == "19,857.2")
    assert (value.top, value.left) == (90.0, 385.0)


def test_extract_joins_spacer_divided_words() -> None:
    pages = extract_positioned_pages(_synthetic_html())
    prose = next(f for f in pages[0].fragments if f.text.startswith("The"))
    assert prose.text == "The willingness of consumers to purchase our products"


def test_extract_drops_decoration_and_dedupes_within_page() -> None:
    fragment = (
        '<div style="position:absolute;left:10px;top:10px;">same</div>'
        '<div style="position:absolute;left:10px;top:10px;">same</div>'
        '<div style="position:absolute;left:0px;top:0px;width:100px;'
        'background-color:#000;">&#160;</div>'
    )
    pages = extract_positioned_pages(f"<div>{fragment}</div>")
    assert pages[0].fragments == (PositionedFragment(10.0, 10.0, "same"),)


def test_extract_excludes_ineligible_coordinates() -> None:
    html = (
        '<div style="position:absolute;left:10%;top:10px;">percent</div>'
        '<div style="position:absolute;top:10px;">no left</div>'
        '<div style="position:absolute;left:10px;top:20pt;">points</div>'
    )
    pages = extract_positioned_pages(html)
    (fragment,) = pages[0].fragments
    assert fragment.text == "points"
    assert fragment.left == 10.0
    assert abs(fragment.top - 20 * 96 / 72) < 1e-9


def test_extract_splits_wrapper_from_nested_fragments() -> None:
    """A wrapper's own text is the residual; nested fragments stay separate."""
    html = (
        '<div style="position:absolute;left:10px;top:10px;">outer '
        '<span style="position:absolute;left:1px;top:1px;">inner</span></div>'
    )
    pages = extract_positioned_pages(html)
    assert [(f.top, f.left, f.text) for f in pages[0].fragments] == [
        (10.0, 10.0, "outer"),
        (11.0, 11.0, "inner"),
    ]


def test_extract_drops_pure_wrapper() -> None:
    html = (
        '<div style="position:absolute;left:0px;top:0px;">'
        '<div style="position:absolute;left:10px;top:10px;">a</div>'
        '<div style="position:absolute;left:10px;top:27px;">b</div></div>'
    )
    pages = extract_positioned_pages(html)
    assert [f.text for f in pages[0].fragments] == ["a", "b"]


def _synthetic_page() -> PositionedPage:
    (page,) = tuple(
        p for p in extract_positioned_pages(_synthetic_html()) if len(p.fragments) > 3
    )
    return page


def test_cluster_rows_join_dollar_offset_row() -> None:
    rows = cluster_page_rows(_synthetic_page())
    net_sales = next(r for r in rows if r.fragments[0].text == "Net sales")
    assert [f.text for f in net_sales.fragments] == [
        "Net sales",
        "$",
        "19,857.2",
        "$",
        "20,094.2",
    ]


def test_cluster_merges_wrapped_label_into_valued_row() -> None:
    rows = cluster_page_rows(_synthetic_page())
    merged = next(r for r in rows if "noncontrolling interests" in r.fragments[0].text)
    assert merged.fragments[0].text == (
        "Net earnings, including earnings attributable to redeemable and "
        "noncontrolling interests"
    )
    assert [f.text for f in merged.fragments[1:]] == ["2,518.6", "2,609.6"]


def test_layout_emits_one_table_band_for_statement_page() -> None:
    blocks = layout_page(_synthetic_page())
    bands = [b for b in blocks if isinstance(b, TableBand)]
    assert len(bands) == 1
    rows = bands[0].rows
    net_sales = next(r for r in rows if r[0] == "Net sales")
    assert net_sales[1:] == ("$ 19,857.2", "$ 20,094.2")
    negative = next(r for r in rows if r[0] == "Divestitures gain, net")
    assert negative[1:] == ("-", "(444.6)")
    operating = next(r for r in rows if r[0] == "Operating profit")
    assert operating[1] == "3,431.7"


def test_layout_keeps_heading_as_flow_line() -> None:
    blocks = layout_page(_synthetic_page())
    assert blocks[0] == FlowLine(text="Consolidated Statements of Earnings")


def test_layout_prose_lines_stay_separate_in_top_order() -> None:
    page = PositionedPage(
        fragments=(
            PositionedFragment(100.0, 48.0, "second line"),
            PositionedFragment(83.0, 48.0, "first line"),
            PositionedFragment(117.0, 48.0, "third line"),
        )
    )
    assert layout_page(page) == (
        FlowLine(text="first line"),
        FlowLine(text="second line"),
        FlowLine(text="third line"),
    )


def test_layout_splits_bands_around_a_section_heading() -> None:
    def row(top: float, label: str, value: str) -> list[PositionedFragment]:
        return [
            PositionedFragment(top, 48.0, label),
            PositionedFragment(top, 385.0, value),
            PositionedFragment(top, 498.0, value),
        ]

    fragments = [
        *row(100.0, "Revenue", "10.0"),
        PositionedFragment(134.0, 48.0, "Section heading"),
        *row(151.0, "Costs", "4.0"),
    ]
    blocks = layout_page(PositionedPage(fragments=tuple(fragments)))
    bands = [b for b in blocks if isinstance(b, TableBand)]
    assert len(bands) == 2
    assert FlowLine(text="Section heading") in blocks


def test_layout_merges_wrapped_label_when_values_sit_on_second_line() -> None:
    page = PositionedPage(
        fragments=(
            PositionedFragment(100.0, 48.0, "After-tax earnings from joint ventures"),
            PositionedFragment(100.0, 416.0, "84.8"),
            PositionedFragment(
                117.0, 48.0, "Net earnings, including earnings attributable to"
            ),
            PositionedFragment(134.0, 48.0, "noncontrolling interests"),
            PositionedFragment(134.0, 393.0, "2,518.6"),
        )
    )
    bands = [b for b in layout_page(page) if isinstance(b, TableBand)]
    assert len(bands) == 1
    rows = bands[0].rows
    assert rows[0][0] == "After-tax earnings from joint ventures"
    assert rows[1] == (
        "Net earnings, including earnings attributable to noncontrolling interests",
        "2,518.6",
    )


def test_layout_does_not_merge_section_heading_into_valued_row() -> None:
    page = PositionedPage(
        fragments=(
            PositionedFragment(100.0, 48.0, "Total current assets"),
            PositionedFragment(100.0, 393.0, "500.0"),
            PositionedFragment(117.0, 48.0, "Current liabilities:"),
            PositionedFragment(134.0, 48.0, "Accounts payable"),
            PositionedFragment(134.0, 393.0, "100.0"),
        )
    )
    blocks = layout_page(page)
    assert FlowLine(text="Current liabilities:") in blocks
    bands = [b for b in blocks if isinstance(b, TableBand)]
    assert all(
        "Current liabilities" not in row[0] for band in bands for row in band.rows
    )


def test_reconstruct_emits_table_the_converter_renders() -> None:
    rebuilt = reconstruct_positioned_html(_synthetic_html())
    rendered, geometries = convert_html_tables_to_ascii_with_metadata(
        rebuilt, convert_to_text=False
    )
    assert geometries
    assert "Net sales" in rendered
    net_sales_line = next(line for line in rendered.split("\n") if "Net sales" in line)
    assert "$ 19,857.2" in net_sales_line
    assert "$ 20,094.2" in net_sales_line


def test_reconstruct_flow_lines_survive_decomposition() -> None:
    text = decompose_html_structures(reconstruct_positioned_html(_synthetic_html()))
    assert "Consolidated Statements of Earnings" in text
    assert "The willingness of consumers to purchase our products" in text
    assert "ACME WIDGETS, INC." in text


def test_reconstruct_leaves_flow_document_unchanged() -> None:
    html = "<div><p>ordinary</p><div style='position:absolute;right:0;'>x</div></div>"
    assert reconstruct_positioned_html(html) == html


def test_reconstruct_works_on_sentinel_segmented_input() -> None:
    rebuilt = reconstruct_positioned_html(insert_page_sentinels(_synthetic_html()))
    text = decompose_html_structures(rebuilt)
    net_sales_line = next(line for line in text.split("\n") if "Net sales" in line)
    assert "19,857.2" in net_sales_line


def test_layout_keeps_checkbox_cover_prose_out_of_bands() -> None:
    page = PositionedPage(
        fragments=(
            PositionedFragment(
                100.0, 48.0, "Indicate by check mark whether the registrant is a"
            ),
            PositionedFragment(
                117.0, 48.0, "complying with any new or revised financial standards"
            ),
            PositionedFragment(117.0, 709.0, "☐"),
            PositionedFragment(
                134.0, 48.0, "provided pursuant to Section 13(a) of the Exchange Act."
            ),
            PositionedFragment(134.0, 709.0, "☑"),
        )
    )
    blocks = layout_page(page)
    assert not any(isinstance(block, TableBand) for block in blocks)
    assert any("complying with any new or revised" in block.text for block in blocks)


def test_layout_keeps_filer_status_checkbox_line_out_of_bands() -> None:
    page = PositionedPage(
        fragments=(
            PositionedFragment(100.0, 59.0, "Large accelerated filer"),
            PositionedFragment(100.0, 182.0, "☑"),
            PositionedFragment(100.0, 233.0, "Accelerated filer"),
            PositionedFragment(100.0, 326.0, "☐"),
            PositionedFragment(100.0, 401.0, "Non-accelerated filer"),
            PositionedFragment(100.0, 518.0, "☐"),
        )
    )
    blocks = layout_page(page)
    assert blocks == (
        FlowLine(
            text="Large accelerated filer ☑ Accelerated filer ☐ Non-accelerated filer ☐"
        ),
    )


def test_layout_keeps_wide_label_value_row_tabular() -> None:
    page = PositionedPage(
        fragments=(
            PositionedFragment(
                100.0, 48.0, "Income tax expense attributable to continuing operations"
            ),
            PositionedFragment(100.0, 416.0, "84.8"),
            PositionedFragment(
                117.0, 48.0, "Selling, general and administrative expenses"
            ),
            PositionedFragment(117.0, 393.0, "3,259.0"),
        )
    )
    bands = [block for block in layout_page(page) if isinstance(block, TableBand)]
    assert len(bands) == 1
    assert bands[0].rows[0][1] == "84.8"


def test_layout_keeps_word_fragmented_prose_line_out_of_bands() -> None:
    fragments = [PositionedFragment(100.0, 48.0, "Cheerios")]
    left = 96.0
    for word in ("Chex", "Cinnamon Toast Crunch", "Cocoa Puffs", "Cookie Crisp"):
        fragments.append(PositionedFragment(100.0, left, ","))
        fragments.append(PositionedFragment(100.0, left + 8.0, word))
        left += 130.0
    page = PositionedPage(fragments=tuple(fragments))
    blocks = layout_page(page)
    assert not any(isinstance(block, TableBand) for block in blocks)


def test_extract_accumulates_positioned_ancestor_offsets() -> None:
    html = (
        '<div style="position:absolute;top:200px;left:40px;">'
        '<div style="position:absolute;top:0px;left:100px;">inner</div>'
        "</div>"
        '<div style="position:absolute;top:10px;left:10px;">outer</div>'
    )
    pages = extract_positioned_pages(html)
    fragments = [fragment for page in pages for fragment in page.fragments]
    assert PositionedFragment(200.0, 140.0, "inner") in fragments
    assert PositionedFragment(10.0, 10.0, "outer") in fragments
