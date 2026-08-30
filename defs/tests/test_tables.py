"""Unit tests for defs.tables package."""

from __future__ import annotations

from defs.tables import (
    GenericTable,
    HTMLTableConverter,
    SimpleTableProcessor,
    process_table,
)


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
