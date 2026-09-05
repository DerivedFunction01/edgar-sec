"""Unit and contract tests for ascii_html geometry-first table renderer."""

from __future__ import annotations

from defs.tables.ascii_html import (
    BorderStyle,
    HorizontalAlign,
    convert_html_table,
    extract_source_table,
)
from defs.tables.ascii_html.borders import (
    extract_border_segments,
    score_header_boundary,
)
from defs.tables.ascii_html.columns import (
    is_structural_spacer,
    resolve_columns,
)
from defs.tables.ascii_html.css import (
    parse_dimension_px,
    parse_style_and_attributes,
)
from defs.tables.ascii_html.geometry import estimate_table_geometry
from defs.tables.ascii_html.spans import build_span_matrix
from defs.tables.ascii_html.text import (
    format_cell_line,
    wrap_cell_text,
)
from defs.text.html import parse_html


def test_parse_dimension_units() -> None:
    """Dimensions in px, pt, in, em, %, and unitless parse correctly into pixels."""
    # px
    px_val, unit, is_pct = parse_dimension_px("100px")
    assert px_val == 100.0
    assert unit == "px"
    assert is_pct is False

    # pt (1pt = 1.3333px)
    pt_val, _, _ = parse_dimension_px("72pt")
    assert pt_val == 96.0

    # in (1in = 96px)
    in_val, _, _ = parse_dimension_px("2in")
    assert in_val == 192.0

    # %
    pct_val, unit, is_pct = parse_dimension_px("50%")
    assert pct_val == 50.0
    assert is_pct is True

    # Unitless HTML attribute
    ul_val, unit, is_pct = parse_dimension_px("250")
    assert ul_val == 250.0
    assert is_pct is False


def test_parse_style_and_attributes() -> None:
    """HTML attributes and inline CSS styles parse into a normalized CellStyle."""
    html = """
    <table>
        <tr>
            <td width="120" align="right" valign="top" style="padding-left: 8px; border-bottom: 2px solid #000; font-weight: bold;">
                <b>$1,234.50</b>
            </td>
        </tr>
    </table>
    """
    tree = parse_html(html)
    node = tree.css_first("td")
    assert node is not None

    style = parse_style_and_attributes(node)
    assert style.width == 120.0
    assert style.text_align is HorizontalAlign.RIGHT
    assert style.padding_left == 8.0
    assert style.border_bottom_width == 2.0
    assert style.border_bottom_style is BorderStyle.SOLID
    assert style.is_bold is True


def test_span_matrix_and_nested_table_isolation() -> None:
    """Rowspan and colspan form correct coordinate slots and nested tables are isolated."""
    html = """
    <table style="width: 100%;">
        <tr>
            <th colspan="2">Consolidated Statement</th>
            <th>Notes</th>
        </tr>
        <tr>
            <td>Revenues</td>
            <td>
                <table><tr><td>Nested Inside</td></tr></table>
            </td>
            <td>1</td>
        </tr>
    </table>
    """
    tree = parse_html(html)
    table_node = tree.css_first("table")
    assert table_node is not None

    source_table, nested_tables = extract_source_table(table_node)
    assert len(source_table.rows) == 2
    assert len(nested_tables) == 1
    assert nested_tables[0].parent_table_index == 0

    matrix, span_groups = build_span_matrix(source_table)
    assert len(matrix) == 2
    assert len(matrix[0]) == 3
    # Top row cell 0 spans columns 0 and 1
    assert matrix[0][0] == matrix[0][1]
    assert matrix[0][2] != matrix[0][0]
    assert len(span_groups) == 1
    assert span_groups[0].start_col == 0
    assert span_groups[0].end_col == 1


def test_geometry_and_column_resolution() -> None:
    """Physical coordinate estimation and horizontal band resolution."""
    html = """
    <table>
        <tr>
            <th style="width: 200px;">Period</th>
            <th style="width: 100px;">Shares</th>
            <th style="width: 100px;">Price</th>
        </tr>
        <tr>
            <td>Q1 2024</td>
            <td align="right">1,000</td>
            <td align="right">$25.50</td>
        </tr>
    </table>
    """
    tree = parse_html(html)
    table_node = tree.css_first("table")
    assert table_node is not None

    source_table, _ = extract_source_table(table_node)
    matrix, span_groups = build_span_matrix(source_table)
    boxes = estimate_table_geometry(source_table, matrix, span_groups)

    assert len(boxes) == 2
    assert len(boxes[0]) == 3
    assert boxes[0][0] is not None
    assert boxes[0][0].width >= 200.0

    active_cols, alignments, spacers = resolve_columns(matrix, boxes)
    assert active_cols == [0, 1, 2]
    assert alignments[0] is HorizontalAlign.LEFT
    assert alignments[1] is HorizontalAlign.RIGHT
    assert alignments[2] is HorizontalAlign.RIGHT
    assert len(spacers) == 0


def test_spacer_retention_policy() -> None:
    """Empty columns with explicit width or padding are retained; inert ones are pruned."""
    # Table with 1 structural spacer column (has width) and 1 inert spacer
    html = """
    <table>
        <tr>
            <td>Line Item</td>
            <td style="width: 15px;"></td>
            <td>Amount</td>
            <td></td>
        </tr>
        <tr>
            <td>Revenue</td>
            <td style="width: 15px;"></td>
            <td>1000</td>
            <td></td>
        </tr>
    </table>
    """
    tree = parse_html(html)
    table_node = tree.css_first("table")
    assert table_node is not None

    source_table, _ = extract_source_table(table_node)
    matrix, _ = build_span_matrix(source_table)

    assert is_structural_spacer(1, matrix) is True
    assert is_structural_spacer(3, matrix) is False


def test_multi_signal_header_scoring_and_double_borders() -> None:
    """Header boundary detection recognizes border color transition and double borders."""
    html = """
    <table>
        <tr>
            <th style="border-bottom: 3px double #1f4e79;"><b>Year</b></th>
            <th style="border-bottom: 3px double #1f4e79;"><b>Amount</b></th>
        </tr>
        <tr>
            <td style="border-bottom: 1px solid #d3d3d3;">2024</td>
            <td style="border-bottom: 1px solid #d3d3d3;">$500</td>
        </tr>
        <tr>
            <td>2023</td>
            <td>$450</td>
        </tr>
    </table>
    """
    tree = parse_html(html)
    table_node = tree.css_first("table")
    assert table_node is not None

    source_table, _ = extract_source_table(table_node)
    matrix, _ = build_span_matrix(source_table)
    active_cols = [0, 1]
    border_segs = extract_border_segments(matrix, active_cols)
    header_rows, divider_style = score_header_boundary(matrix, active_cols, border_segs)

    assert header_rows == 1
    assert divider_style == BorderStyle.DOUBLE

    # Render result should have '==' divider
    res = convert_html_table(html)
    assert "===" in res.ascii_text


def test_text_wrapping_and_budget() -> None:
    """Word wrapping wraps long text without breaking words and obeys RenderBudget."""
    text = "Research and development expenses for current operating cycle"
    wrapped = wrap_cell_text(text, width=25)
    assert len(wrapped) >= 2
    assert all(len(line) <= 25 for line in wrapped)

    # Padding and alignment
    right_aligned = format_cell_line("1,234.50", width=12, align=HorizontalAlign.RIGHT)
    assert len(right_aligned) == 12
    assert right_aligned == "    1,234.50"


def test_wrap_normalizes_non_breaking_spaces_before_layout() -> None:
    """Non-breaking source spaces must not turn adjacent words into one token."""
    wrapped = wrap_cell_text(
        "Weighted\xa0Average Grant-Date\xa0Fair\xa0Value", width=20
    )
    assert not any(line.endswith("Gra") for line in wrapped)
    assert not any(line.startswith("nt-Date") for line in wrapped)
    assert "Grant-Date" in " ".join(wrapped)


def test_canonical_ascii_table_rendering() -> None:
    """Full v2 table rendering emits canonical <TABLE> format with alignment headers."""
    html = """
    <table>
        <tr>
            <th align="left" style="border-bottom: 1px solid black;"><b>Component</b></th>
            <th align="right" style="border-bottom: 1px solid black;"><b>2024</b></th>
            <th align="right" style="border-bottom: 1px solid black;"><b>2023</b></th>
        </tr>
        <tr>
            <td>Total revenues</td>
            <td align="right">1,200</td>
            <td align="right">1,100</td>
        </tr>
        <tr>
            <td>Cost of sales</td>
            <td align="right">400</td>
            <td align="right">350</td>
        </tr>
    </table>
    """
    res = convert_html_table(html)
    assert res.confidence >= 0.80
    assert "<TABLE>" in res.ascii_text
    assert "</TABLE>" in res.ascii_text
    assert "Component" in res.ascii_text
    assert "Total revenues" in res.ascii_text
    assert "1,200" in res.ascii_text
    assert "---" in res.ascii_text


def test_convert_html_tables_to_ascii_document_facade() -> None:
    """convert_html_tables_to_ascii converts all tables across a document."""
    html = """
    <html>
        <body>
            <p>Financial Statement Note</p>
            <table>
                <tr>
                    <th><b>Line Item</b></th>
                    <th><b>Amount</b></th>
                </tr>
                <tr>
                    <td>Revenue</td>
                    <td>1000</td>
                </tr>
            </table>
            <p>Second Schedule</p>
            <table>
                <tr>
                    <th><b>Asset</b></th>
                    <th><b>Fair Value</b></th>
                </tr>
                <tr>
                    <td>Securities</td>
                    <td>500</td>
                </tr>
            </table>
        </body>
    </html>
    """
    from defs.tables.ascii_html import convert_html_tables_to_ascii

    v2_doc = convert_html_tables_to_ascii(html)
    assert "<TABLE>" in v2_doc
    assert "Financial Statement Note" in v2_doc
    assert "Revenue" in v2_doc
    assert "Securities" in v2_doc
    assert "500" in v2_doc


def test_indent_preservation_and_compact_layout() -> None:
    """CSS padding-left/margin-left and &nbsp; are preserved as visual indentation in ASCII output."""
    html = """
    <table>
        <tr>
            <th>Line Item</th>
            <th>Amount</th>
        </tr>
        <tr>
            <td style="padding: 2px 1pt 2px 19pt;">Indented Category</td>
            <td align="right">150</td>
        </tr>
        <tr>
            <td style="padding-left: 30pt;">Deeply Indented Sub-item</td>
            <td align="right">50</td>
        </tr>
        <tr>
            <td>&nbsp;&nbsp;&nbsp;&nbsp;Non-breaking Space Indented</td>
            <td align="right">25</td>
        </tr>
        <tr>
            <td style="padding: 2px 1pt;"><div style="padding-left: 11.25pt;">Inner Div Indented Signature</div></td>
            <td align="right">10</td>
        </tr>
    </table>
    """
    res = convert_html_table(html)
    lines = res.ascii_text.splitlines()

    # Find the data rows and assert leading whitespace indentation is preserved
    indented_cat_line = next(line for line in lines if "Indented Category" in line)
    deeply_indented_line = next(
        line for line in lines if "Deeply Indented Sub-item" in line
    )
    nbsp_line = next(line for line in lines if "Non-breaking Space Indented" in line)
    inner_div_line = next(
        line for line in lines if "Inner Div Indented Signature" in line
    )

    assert (
        indented_cat_line.startswith("    Indented Category")
        or "  Indented Category" in indented_cat_line
    )
    assert "Deeply Indented Sub-item" in deeply_indented_line
    assert "Non-breaking Space Indented" in nbsp_line
    assert inner_div_line.startswith(
        ("  Inner Div Indented Signature", "    Inner Div Indented Signature")
    )


def test_effective_indentation_normalization() -> None:
    """Excessive padding/indentation (e.g. 0, 4, 8 spaces) normalizes to discrete 2-space tiers (0, 2, 4)."""
    html = """
    <table>
        <tr>
            <th>Year Ended June 30,</th>
            <th>2025</th>
        </tr>
        <tr>
            <td style="text-indent: 12.25pt;">Revenue:</td>
            <td>100</td>
        </tr>
        <tr>
            <td style="text-indent: 24.5pt;">Product</td>
            <td>60</td>
        </tr>
        <tr>
            <td style="text-indent: 24.5pt;">Service</td>
            <td>40</td>
        </tr>
        <tr>
            <td style="text-indent: 36pt;">Total revenue</td>
            <td>100</td>
        </tr>
    </table>
    """
    res = convert_html_table(html)
    lines = res.ascii_text.splitlines()

    rev_line = next(line for line in lines if "Revenue:" in line)
    prod_line = next(line for line in lines if "Product" in line)
    tot_line = next(line for line in lines if "Total revenue" in line)

    # 0, 4, 8 spaces normalize down to 0, 2, 4 spaces
    assert rev_line.startswith("  Revenue:")
    assert prod_line.startswith("    Product")
    assert tot_line.startswith("    Total revenue")


def test_rowspan_header_deduplication() -> None:
    """Multi-row header cells with rowspan > 1 emit text once and do not duplicate across continuation rows."""
    html = """
    <table>
        <tr>
            <th rowspan="2"><b>Period ended</b></th>
            <th colspan="2"><b>2025</b></th>
        </tr>
        <tr>
            <th>Amount</th>
            <th>Rate</th>
        </tr>
        <tr>
            <td>Category 1</td>
            <td>100</td>
            <td>5%</td>
        </tr>
    </table>
    """
    res = convert_html_table(html)
    assert res.ascii_text.count("Period ended") == 1


def test_nbsp_normalization_no_mid_word_wrap() -> None:
    """&nbsp; joined words wrap at word boundaries, not mid-word, and no U+00A0 leaks into output."""
    html = """
    <table>
        <tr>
            <th colspan="2">Weighted&#xa0;Average<br/>Grant-Date&#xa0;Fair&#xa0;Value</th>
        </tr>
        <tr>
            <td>100</td>
            <td>200</td>
        </tr>
    </table>
    """
    res = convert_html_table(html)
    assert "\xa0" not in res.ascii_text
    lines = res.ascii_text.splitlines()
    header_lines = [l for l in lines if "Weighted" in l or "Grant-Date" in l]
    assert len(header_lines) == 1
    assert "Weighted Average Grant-Date Fair Value" in header_lines[0]


def test_hyphen_fallback_no_mid_word_chop() -> None:
    """Hyphenated tokens wider than the column break at hyphens before mid-word chopping."""
    from defs.tables.ascii_html.text import wrap_cell_text

    text = "Fully taxable-equivalent adjustments (a)"
    wrapped = wrap_cell_text(text, width=10)
    assert len(wrapped) >= 3
    for line in wrapped:
        assert len(line) <= 10
    assert wrapped[0] == "Fully"
    assert wrapped[1] == "taxable-"
    joined = " ".join(wrapped)
    assert "taxable-eq" not in joined


def test_header_tier_balance_pass() -> None:
    """Sibling span headers in the same row receive more balanced column widths."""
    from defs.tables.ascii_html.text import compute_column_widths

    grid = [
        ["Short", "", "Long Header Here", ""],
        ["1", "2", "3", "4"],
    ]
    alignments = [HorizontalAlign.LEFT] * 4
    span_constraints = [
        (0, [0, 1], "Short"),
        (0, [2, 3], "Long Header Here"),
    ]
    widths, _ = compute_column_widths(
        grid,
        alignments,
        span_constraints=span_constraints,
    )
    first_block = sum(widths[:2])
    second_block = sum(widths[2:])
    assert first_block >= 6
    assert second_block >= 6
    assert abs(first_block - second_block) <= 2


def test_nonempty_span_origin_is_not_pruned() -> None:
    """A year span remains visible when its origin would otherwise be zero-width."""
    from defs.tests.query_table_corpus import _records

    record = next(
        item for item in _records() if item["table_id"] == "jpmorgan_2025_table_0098"
    )
    output = convert_html_table(record["html"]).ascii_text
    year_line = next(line for line in output.splitlines() if "2025" in line)
    assert "2024" in year_line
    assert "2023" in year_line
    assert any("except ratios)" in line for line in output.splitlines())
    assert output.count("equivalent") == 3
    assert output.count("adjustments") == 3


def test_affix_only_columns_do_not_fragment_dividers() -> None:
    """Affix handling preserves parseable divider cell boundaries."""
    from defs.tests.query_table_corpus import _records

    target_ids = {
        "msft_2025_table_0019",
        "msft_2025_table_0023",
        "msft_2025_table_0024",
        "msft_2025_table_0030",
        "lmt_2025_table_0014",
        "lmt_2025_table_0032",
    }
    records = [item for item in _records() if item["table_id"] in target_ids]
    assert {item["table_id"] for item in records} == target_ids

    for record in records:
        output = convert_html_table(record["html"]).ascii_text
        divider_lines = [
            line
            for line in output.splitlines()
            if line.strip() and set(line.strip()) <= {"-", "=", " "}
        ]
        assert divider_lines
        assert any("  " in line for line in divider_lines)
        if record["table_id"] in {"lmt_2025_table_0014", "lmt_2025_table_0032"}:
            assert all(" - " not in line for line in divider_lines)


def test_prefix_column_closes_following_divider_gap() -> None:
    """A dollar-prefix column connects to its following numeric divider span."""
    from defs.tests.query_table_corpus import _records

    record = next(
        item for item in _records() if item["table_id"] == "msft_2025_table_0060"
    )
    output = convert_html_table(record["html"]).ascii_text
    divider_lines = [
        line for line in output.splitlines() if line and set(line) <= {"-", "=", " "}
    ]
    assert any(line == "-" * len(line) for line in divider_lines)


def test_healed_divider_lines_from_templates() -> None:
    """Fragmented dividers are healed in 2-year, 3-year, and merged-header tables."""
    from defs.tests.query_table_corpus import _records

    target_ids = {
        "tgt_2026_table_0114",
        "tgt_2026_table_0120",
        "tgt_2026_table_0140",
        "tgt_2026_table_0162",
    }
    records = {
        item["table_id"]: item for item in _records() if item["table_id"] in target_ids
    }
    assert set(records.keys()) == target_ids

    # 1. 2-year table (tgt_2026_table_0114)
    out_114 = convert_html_table(records["tgt_2026_table_0114"]["html"]).ascii_text
    divs_114 = [
        line
        for line in out_114.splitlines()
        if line and set(line) <= {"-", "=", " "} and set(line) & {"-", "="}
    ]
    # Top divider and header bottom divider must be clean and not have isolated '-' fragments
    assert "  -  " not in divs_114[0]
    assert divs_114[0] == divs_114[1]

    # 2. 2-year table (tgt_2026_table_0120)
    out_120 = convert_html_table(records["tgt_2026_table_0120"]["html"]).ascii_text
    divs_120 = [
        line
        for line in out_120.splitlines()
        if line and set(line) <= {"-", "=", " "} and set(line) & {"-", "="}
    ]
    assert "  -  " not in divs_120[0]
    assert divs_120[0] == divs_120[1]

    # 3. 3-year / rate reconciliation table (tgt_2026_table_0140)
    out_140 = convert_html_table(records["tgt_2026_table_0140"]["html"]).ascii_text
    divs_140 = [
        line
        for line in out_140.splitlines()
        if line and set(line) <= {"-", "=", " "} and set(line) & {"-", "="}
    ]
    assert "  -  " not in divs_140[0]
    assert divs_140[0] == divs_140[2]

    # 4. Multi-level merged header table (tgt_2026_table_0162)
    out_162 = convert_html_table(records["tgt_2026_table_0162"]["html"]).ascii_text
    divs_162 = [
        line
        for line in out_162.splitlines()
        if line and set(line) <= {"-", "=", " "} and set(line) & {"-", "="}
    ]
    # Row 0 top and bottom dividers should span across the merged superheaders (3 runs, 2 runs)
    assert len(divs_162[0].split()) == 3
    assert len(divs_162[1].split()) == 2
    # Subheaders (row 1) and data rows should preserve the 4 separate column bands (5 runs)
    assert len(divs_162[2].split()) == 5


def test_balanced_line_wrapping_optimizes_headroom() -> None:
    """Balanced multi-line wrapping prevents wide headers from choking sibling date columns."""
    from defs.tests.query_table_corpus import _records

    record = next(
        item for item in _records() if item["table_id"] == "jnj_2025_table_0112"
    )
    output = convert_html_table(record["html"]).ascii_text
    lines = output.splitlines()

    # Date headers should fit completely on one line and not be forced onto two lines
    date_line = next(line for line in lines if "December 28, 2025" in line)
    assert "December 29, 2024" in date_line
    # Long superheader should wrap into balanced lines without ballooning to 80+ width
    assert any("Location of Gain or (Loss) Reclassified from" in line for line in lines)
    assert any("Accumulated OCI Into Income" in line for line in lines)


def test_short_headers_do_not_wrap_when_budget_allows() -> None:
    """Short comparison headers fit on a single line when table budget has headroom."""
    from defs.tests.query_table_corpus import _records

    record = next(
        item for item in _records() if item["table_id"] == "jnj_2025_table_0178"
    )
    output = convert_html_table(record["html"]).ascii_text
    lines = output.splitlines()
    header_line = next(line for line in lines if "’25 vs. ’24" in line)
    assert "’24 vs. ’23" in header_line


def test_footnote_column_dividers_heal_to_full_columns() -> None:
    """Fragmented footnote/affix runs (<= 3 chars) heal against full-column templates."""
    from defs.tests.query_table_corpus import _records

    record = next(
        item for item in _records() if item["table_id"] == "jpmorgan_2025_table_0065"
    )
    output = convert_html_table(record["html"]).ascii_text
    divs = [
        line
        for line in output.splitlines()
        if line and set(line) <= {"-", "=", " "} and set(line) & {"-", "="}
    ]
    # Full-table major dividers should be unified across the 4 primary columns (3 double-spaces)
    full_divs = [d for d in divs if len(d) > 40]
    assert len(full_divs) >= 4
    assert all(d.count("  ") == 3 for d in full_divs)
    # Single-column subheader dividers are preserved without artificial gaps
    assert any(d == "--------------------------------------" for d in divs)


def test_inline_elements_do_not_inject_artificial_spaces() -> None:
    """Inline formatting (e.g. small-caps spans, signature slashes) merge naturally without artificial spaces."""
    from defs.tests.query_table_corpus import _records

    record = next(
        item for item in _records() if item["table_id"] == "goog_2025_table_0185"
    )
    output = convert_html_table(record["html"]).ascii_text
    # Names split across styling spans (e.g. <span>S</span><span>UNDAR</span>) should not have inner spaces
    assert "SUNDAR PICHAI" in output
    assert "S UNDAR" not in output
    assert "ANAT ASHKENAZI" in output
    assert "A NAT" not in output
    assert "AMIE THUENER O'TOOLE" in output
    assert "T HUENER" not in output
    assert "/S/" in output
    assert "/ S /" not in output


def test_unanchored_divider_fragments_are_pruned() -> None:
    """Phantom divider fragments in columns without text are pruned."""
    from defs.tests.query_table_corpus import _records

    record = next(
        item for item in _records() if item["table_id"] == "msft_2025_table_0055"
    )
    output = convert_html_table(record["html"]).ascii_text
    # Divider line should not have orphan ' - ' fragments between columns
    assert "  -  " not in output
    assert (
        "--------------------------------------  ----------  ----------  ----------"
        in output
    )


def test_data_row_cells_not_misclassified_as_header_bands() -> None:
    """Spanned cells in data rows are not falsely rewritten by header band span repairs."""
    from defs.tests.query_table_corpus import _records

    record = next(
        item for item in _records() if item["table_id"] == "apple_2025_table_0059"
    )
    output = convert_html_table(record["html"]).ascii_text
    assert "32.1***           Section 1350 Certifications of Chief Executive" in output


def test_data_row_with_footnote_spans_preserves_numeric_values() -> None:
    """Data rows containing spanned footnotes (e.g. jpmorgan table 0065) preserve all numeric data."""
    from defs.tests.query_table_corpus import _records

    record = next(
        item for item in _records() if item["table_id"] == "jpmorgan_2025_table_0065"
    )
    output = convert_html_table(record["html"]).ascii_text
    assert (
        "Total net revenue                             $ 182,447    $ 177,556 (g)      $ 158,104"
        in output
    )
    assert (
        "Total noninterest expense                        95,640       91,797 (g)         87,172"
        in output
    )


def test_multi_column_header_span_with_zero_width_origin_preserves_text() -> None:
    """Header spans across columns where origin is zero-width (e.g. msft 0015) preserve text."""
    from defs.tests.query_table_corpus import _records

    record = next(
        item for item in _records() if item["table_id"] == "msft_2025_table_0015"
    )
    output = convert_html_table(record["html"]).ascii_text
    assert "Percentage" in output
    assert "Change" in output


def test_hidden_elements_filtered_preserves_header_band_alignment() -> None:
    """Tables with display:none spacer elements (e.g. jpmorgan 0098) correctly align year bands."""
    from defs.tests.query_table_corpus import _records

    record = next(
        item for item in _records() if item["table_id"] == "jpmorgan_2025_table_0098"
    )
    output = convert_html_table(record["html"]).ascii_text
    lines = output.splitlines()
    year_line = next(line for line in lines if "2025" in line and "2024" in line)
    # The header line should have exactly one occurrence of each year
    assert year_line.count("2025") == 1
    assert year_line.count("2024") == 1
    assert year_line.count("2023") == 1


def test_prose_columns_expand_without_artificial_line_wrapping() -> None:
    """Prose description columns (e.g. msft 0006, lmt 0071) expand into available table headroom."""
    from defs.tests.query_table_corpus import _records

    # MSFT 0006 TOC description
    rec_msft = next(
        item for item in _records() if item["table_id"] == "msft_2025_table_0006"
    )
    out_msft = convert_html_table(rec_msft["html"]).ascii_text
    assert "Item 1.   Business" in out_msft

    # LMT 0071 Exhibit Index description
    rec_lmt = next(
        item for item in _records() if item["table_id"] == "lmt_2025_table_0071"
    )
    out_lmt = convert_html_table(rec_lmt["html"]).ascii_text
    assert (
        "3.1  Charter of Lockheed Martin Corporation, as amended by Articles of Amendment"
        in out_lmt
    )
