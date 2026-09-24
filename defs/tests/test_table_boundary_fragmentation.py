from __future__ import annotations

from defs.text.reflow import reflow_ascii
from defs.text.reflow.types import ReflowPolicy


def test_interleaved_fiscal_period_subheadings_unify() -> None:
    # A stock price or sales schedule broken into Fiscal 1998 and Fiscal 1999
    text = (
        "                            High          Low\n"
        "                            ----          ---\n"
        "Fiscal 1998\n"
        "- -----------\n"
        "First  Quarter              3.50          1.50\n"
        "Second Quarter              1.958         1.562\n"
        "Third  Quarter              1.50          1.125\n"
        "Fourth Quarter              1.187          .83\n"
        "\n"
        "Fiscal 1999\n"
        "- -----------\n"
        "First  Quarter              1.312          .771\n"
    )

    result = reflow_ascii(
        text, body_start_line=0, policy=ReflowPolicy(tag_untagged_tables=True)
    )

    assert result.text.count("<TABLE>") == 1
    assert "High          Low" in result.text
    assert "Fiscal 1998" in result.text
    assert "Fiscal 1999" in result.text
    assert "First  Quarter              1.312          .771" in result.text


def test_unit_header_with_period_columns_absorbed() -> None:
    text = (
        "             Consolidated Balance Sheets\n"
        "             (in thousands, except per share data)\n"
        "\n"
        "                                     2003       2002\n"
        "                                     ----       ----\n"
        "Cash and cash equivalents          $1,200     $1,100\n"
        "Total current assets                4,500      3,900\n"
    )

    result = reflow_ascii(
        text, body_start_line=0, policy=ReflowPolicy(tag_untagged_tables=True)
    )

    assert result.text.count("<TABLE>") == 1
    assert "(in thousands, except per share data)" in result.text
    assert "2003       2002" in result.text
    assert "Total current assets" in result.text
