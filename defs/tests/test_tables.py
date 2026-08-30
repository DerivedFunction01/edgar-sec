"""Unit tests for defs.tables package."""

from __future__ import annotations

import re

from defs.tables import (
    ALL_CURRENCY_SYMBOLS,
    FINANCIAL_PLACEHOLDERS,
    GenericTable,
    HTMLTableConverter,
    SimpleTableProcessor,
    convert_html_tables_to_ascii,
    is_financial_placeholder,
    is_numeric_cell,
    process_table,
)
from defs.tables.currencies import MAJOR_CURRENCIES
from defs.tables.repair import clean_and_merge_symbols


def test_generic_table_build():
    headers = ["Item", "2008", "2009"]
    data_rows = [
        ["Revenue", "100", "120"],
        ["Net Income", "20", "25"],
    ]
    widths = [15, 8, 8]
    alignments = ["l", "r", "r"]
    table = GenericTable(
        headers=headers,
        data_rows=data_rows,
        widths=widths,
        alignments=alignments,
        title="Financial Summary",
    )
    result = table.build()

    assert "<TABLE>" in result
    assert "<CAPTION>\nFinancial Summary</CAPTION>" in result
    assert "<S>" in result
    assert "<C>" in result
    assert "Revenue" in result
    assert "Net Income" in result
    assert "</TABLE>" in result


def test_html_table_converter():
    grid = [
        ["Line Item", "FY 2005", "FY 2006"],
        ["Cash", "$ 1,000", "$ 1,500"],
        ["Debt", "$ 500", "$ 400"],
    ]
    converter = HTMLTableConverter(grid=grid, title="Balance Sheet", header_row_count=1)
    generic = converter.to_generic_table()
    built = generic.build()

    assert "<TABLE>" in built
    assert "Balance Sheet" in built
    assert "Line Item" in built
    assert "$ 1,000" in built


def test_html_table_converter_dynamic_alignment_and_trimming():
    # Column 0: Code, Column 1: Empty spacer, Column 2: Text Description, Column 3: Numbers
    grid = [
        ["Code", "", "Description", "FY 2025"],
        ["A1", "", "Consumer Health Products", "$ 1,200"],
        ["B2", "", "Medical Devices and Diagnostics", "$ 3,400"],
    ]
    converter = HTMLTableConverter(
        grid=grid, title="Segment Summary", header_row_count=1
    )
    generic = converter.to_generic_table()
    built = generic.build()

    # Verify spacer column was trimmed (3 columns remain, not 4)
    assert len(generic.widths) == 3
    # Verify Col 0 (Code) and Col 1 (Description) are left-aligned, Col 2 is right-aligned
    assert generic.alignments == ["l", "l", "r"]
    assert "Consumer Health Products" in built
    assert "$ 1,200" in built


def test_html_table_converter_width_capping():
    # Long narrative footnote in cell
    grid = [
        ["Category", "Long Description Footnote"],
        [
            "Item",
            "This is an extremely long footnote text describing accounting policies in extensive detail spanning well over sixty characters in a single cell.",
        ],
    ]
    converter = HTMLTableConverter(grid=grid, max_text_col_width=40)
    generic = converter.to_generic_table()

    # Column 1 width should be capped at 40
    assert generic.widths[1] <= 40


def test_html_table_conversion_debug_reports_header_boundary(capsys):
    html = """
    <table>
      <tr><th></th><th>2025</th></tr>
      <tr><th>Amount</th><th>Value</th></tr>
      <tr><td>The effects of fair value hedging:</td><td></td></tr>
      <tr><td>Gain (Loss) on fair value hedging relationship:</td><td></td></tr>
      <tr><td>Hedged items</td><td>338</td></tr>
      <tr><td>Other hedged items</td><td>339</td></tr>
      <tr><td>Total hedged items</td><td>340</td></tr>
      <tr><td>Final hedged items</td><td>341</td></tr>
    </table>
    """

    result = convert_html_tables_to_ascii(html, debug=True)

    diagnostics = capsys.readouterr().err
    assert "source row 2" in diagnostics
    assert "Gain (Loss) on fair value hedging relationship:" in diagnostics
    assert re.search(r"selected header_count=2", diagnostics)
    assert "converted output" in diagnostics
    assert "<TABLE>" in result


def test_html_table_conversion_preserves_change_columns():
    html = """
    <table>
      <tr><th></th><th>2025</th><th>Change</th><th>2024</th></tr>
      <tr><td>Research and development</td><td>$ 34,550</td><td>10 %</td><td>$ 31,370</td></tr>
      <tr><td>Selling, general and administrative</td><td>$ 27,601</td><td>6 %</td><td>$ 26,097</td></tr>
      <tr><td>Total operating expenses</td><td>$ 62,151</td><td>8 %</td><td>$ 57,467</td></tr>
    </table>
    """

    result = convert_html_tables_to_ascii(html)

    assert "2025" in result and "Change" in result and "2024" in result
    assert "34,550" in result and "10%" in result
    assert "34,550 10%" not in result


def test_percentage_normalization_preserves_prose():
    assert clean_and_merge_symbols(["Deposits as a % of total liabilities"])[0] == (
        "Deposits as a % of total liabilities"
    )


def test_html_percentage_normalization_preserves_prose():
    html = """
    <table>
      <tr><th>Metric</th><th>Total % of IG</th></tr>
      <tr><td>Coverage</td><td>10 %</td></tr>
      <tr><td>Deposits as a % of total liabilities</td><td>50 %</td></tr>
      <tr><td>Other</td><td>25 %</td></tr>
    </table>
    """

    result = convert_html_tables_to_ascii(html)

    assert "10%" in result and "50%" in result and "25%" in result
    assert "Total % of IG" in result
    assert "Deposits as a % of total liabilities" in result


def test_registration_table_delegator_handles_text_only_columns():
    html = """
    <table>
      <tr><th>Title of each class</th><th>Trading Symbol(s)</th>
          <th>Name of each exchange on which registered</th></tr>
      <tr><td>Common stock</td><td>JPM</td><td>The New York Stock Exchange</td></tr>
      <tr><td>Depositary Shares, each representing a one-four hundredth interest in a share</td>
          <td>JPM PR D</td><td>The New York Stock Exchange</td></tr>
    </table>
    """

    result = convert_html_tables_to_ascii(html)

    assert "<TABLE>" in result
    assert "Title of each class" in result
    assert "JPM PR D" in result
    assert "a one-four hundredth" in result
    assert "interest in a share" in result
    assert "aone-four" not in result

    plural_result = convert_html_tables_to_ascii(
        html.replace("Trading Symbol(s)", "Trading Symbol")
    )
    assert "JPM PR D" in plural_result
    assert "<TABLE>" in plural_result


def test_simple_table_processor_parsing():
    raw_table = """
<TABLE>
<CAPTION>
Operating Results (in thousands)
</CAPTION>
Description                     2008        2009
<S>                             <C>         <C>
Product Sales                   $ 50,000    $ 65,000
Service Revenue                   10,000      12,500
Total Revenue                   $ 60,000    $ 77,500
</TABLE>
"""
    processor = SimpleTableProcessor(raw_table)
    assert not processor.invalid_table
    assert processor.caption == "Operating Results (in thousands)"
    assert processor.global_multiplier == 1000.0
    assert processor.table_currency == "USD"

    data = processor.get_data()
    assert len(data) == 3
    # Check currency merging: '$ 50,000' -> '$50,000'
    assert data[0][0] == "Product Sales"
    assert data[0][1] == "$50,000"
    assert data[0][2] == "$65,000"

    years = processor.get_years()
    assert 2008 in years.values()
    assert 2009 in years.values()


def test_simple_table_processor_split_number_repair():
    raw_table = """
<TABLE>
Item                             Amount
<S>                              <C>
Inventory                        33 ,252
Accounts Payable                 12 ,000
</TABLE>
"""
    result = process_table(raw_table)
    data = result["data"]
    assert len(data) == 2
    assert "33,252" in data[0] or any("33,252" in cell for cell in data[0])


def test_simple_table_processor_row_healing():
    raw_table = """
<TABLE>
<S>                             <C>
Long-term debt,
less current portion            500
Capital lease obligations       100
</TABLE>
"""
    processor = SimpleTableProcessor(raw_table)
    data = processor.get_data()
    assert len(data) >= 1
    # Check that multi-line text was healed
    assert any("Long-term debt" in row[0] for row in data)


def test_currency_and_multiplier_detection():
    raw_table = """
<TABLE>
<CAPTION>
European Operations in millions (€)
</CAPTION>
Segment                         2010
<S>                             <C>
Germany                         € 150
France                          € 120
</TABLE>
"""
    processor = SimpleTableProcessor(raw_table)
    assert processor.table_currency == "EUR"
    assert processor.global_multiplier == 1_000_000.0
    data = processor.get_data()
    assert len(data) == 2
    assert "€150" in data[0][1]


def test_percentage_column_normalization():
    raw_table = """
<TABLE>
Metric                          Percentage
<S>                             <C>
Gross Margin                    45.5
Operating Margin                12.3
</TABLE>
"""
    processor = SimpleTableProcessor(raw_table)
    data = processor.get_data()
    assert len(data) == 2
    assert data[0][1] == "45.5%"
    assert data[1][1] == "12.3%"


def test_table_to_string_reconstruction():
    raw_table = """
<TABLE>
<CAPTION>
Summary
</CAPTION>
Item                            2007
<S>                             <C>
Assets                          $ 500
</TABLE>
"""
    processor = SimpleTableProcessor(raw_table)
    rebuilt = processor.to_string()
    assert "<TABLE>" in rebuilt
    assert "<CAPTION>\nSummary</CAPTION>" in rebuilt
    assert "$500" in rebuilt


def test_html_conversion_resolves_rowspan_and_colspan():
    html = """
    <table><tr><th rowspan="2">Item</th><th colspan="2">Years</th></tr>
    <tr><th>2024</th><th>2025</th></tr>
    <tr><td>Revenue</td><td>$ 10</td><td>$ 12</td></tr>
    <tr><td>Costs</td><td>$ 4</td><td>$ 5</td></tr></table>
    """
    result = convert_html_tables_to_ascii(html)
    assert "Years" in result and "2024" in result and "2025" in result
    assert "Revenue" in result and "$10" in result


def test_html_conversion_merges_split_currency_and_footnotes():
    html = """
    <table><tr><th>Item</th><th>Amount</th><th>Ref</th></tr>
    <tr><td>Cash</td><td>$</td><td>2,559,320</td><td>(a)</td></tr>
    <tr><td>Debt</td><td>$</td><td>3,803</td><td></td></tr>
    <tr><td>Other</td><td>$</td><td>100</td><td>(b)</td></tr></table>
    """
    result = convert_html_tables_to_ascii(html)
    assert "$2,559,320" in result and "(a)" in result
    assert "$3,803" in result


def test_html_conversion_unwraps_bullets_and_toc():
    html = """
    <table><tr><td>1.</td><td>First disclosure</td></tr>
    <tr><td>2.</td><td>Second disclosure</td></tr></table>
    <table><tr><td>PART I</td><td>Page</td></tr>
    <tr><td>Item 1 ...</td><td>4</td></tr></table>
    """
    result = convert_html_tables_to_ascii(html)
    assert "• First disclosure" in result
    assert "PART I" in result and "<TABLE>" not in result


def test_html_conversion_preserves_section_headers_and_stub_alignment():
    html = """
    <table><tr><th>Description</th><th>2024</th><th>2025</th></tr>
    <tr><td colspan="3">North America</td></tr>
    <tr><td>Revenue</td><td>10</td><td>12</td></tr>
    <tr><td>Margin</td><td>20%</td><td>25%</td></tr></table>
    """
    result = convert_html_tables_to_ascii(html)
    assert "North America" in result and "Revenue" in result
    assert "<S>" in result


def test_table_token_registry_covers_all_currency_metadata():
    registered_symbols = {
        symbol
        for currency in MAJOR_CURRENCIES.values()
        for symbol in currency["symbols"]
    }
    assert registered_symbols == ALL_CURRENCY_SYMBOLS
    for symbol in registered_symbols:
        assert is_numeric_cell(f"{symbol}123")


def test_table_token_registry_has_one_placeholder_policy():
    for placeholder in FINANCIAL_PLACEHOLDERS:
        assert is_financial_placeholder(placeholder)
        assert is_numeric_cell(placeholder)
