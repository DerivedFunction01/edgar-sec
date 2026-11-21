"""Tests proving statement rendering: scaled tables, wrapping, markdown, labels."""

from tests.apps.client.xbrl.xbrl_support import (
    _create_labelled_xbrl_facade,
    _create_xbrl_facade,
)


def test_statement_render_scales_wraps_and_heads() -> None:
    """Scaled table: units note, filing header, wrapped humanized labels."""
    income = _create_xbrl_facade("msft").statements.income_statement()
    table = income.render_table()
    assert table.startswith("MICROSOFT CORPORATION")
    assert "(in millions)" in table
    assert "$245,122" in table
    assert "Revenue From Contract With" in table
    assert "Customer Excluding Assessed Tax" in table
    assert "RevenueFromContractWithCustomer" not in table
    full = income.render_table(scaled=False)
    assert "$245,122,000,000" in full
    assert "(in millions)" not in full


def test_jpm_long_labels_wrap_instead_of_truncating() -> None:
    """A label longer than the column wraps whole; nothing is truncated."""
    table = _create_xbrl_facade("jpm").statements.balance_sheet().render_table()
    assert "Federal Funds Sold And Securities" in table
    assert "Purchased Under Agreements To Resell" in table
    assert "FederalFundsSoldAndSecuritiesPurchasedUn" not in table


def test_statement_markdown_pipe_table_matches_scaled_totals() -> None:
    """Markdown export parses as a pipe table with the scaled totals."""
    income = _create_xbrl_facade("msft").statements.income_statement()
    md = income.to_markdown()
    assert md.startswith("MICROSOFT CORPORATION")
    assert "(in millions)" in md
    pipe_lines = [line for line in md.splitlines() if line.startswith("|")]
    assert pipe_lines[0].startswith("| Financial Concept |")
    assert set(pipe_lines[1].replace("|", " ").split()) == {"---"}
    revenue = next(line for line in pipe_lines if "Revenue From Contract" in line)
    cells = [cell.strip() for cell in revenue.strip().strip("|").split("|")]
    assert cells[-2] == "$245,122"
    assert cells[-1] == "+15.7%"


def test_comparison_markdown_carries_labels_and_ratios() -> None:
    """Comparison markdown heads with the metric column and ratio rows."""
    msft = _create_xbrl_facade("msft")
    md = msft.compare([_create_xbrl_facade("aapl")]).to_markdown()
    assert md.splitlines()[0].startswith("| Metric |")
    assert "Operating Margin" in md
    assert "Return on Assets (ROA)" in md


def test_xbrl_facade_with_labels_uses_standard_en_us_label() -> None:
    """Verify labelled bundles construct and standard en-US labels win."""
    xbrl = _create_labelled_xbrl_facade()

    view = xbrl.graph("us-gaap:Assets")
    assert view.root is not None
    assert view.root.label == "Total Assets (Standard)"
    assert view.nodes["us-gaap:AssetsCurrent"].label == "Current Assets (Terse)"

    balance_sheet = xbrl.statements.balance_sheet()
    assert balance_sheet.root is not None
    assert balance_sheet.root.label == "Total Assets (Standard)"
