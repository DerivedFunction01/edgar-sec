"""Unit and contract tests for table continuation detection and pre-render fusion."""

from __future__ import annotations

from defs.tables.ascii_html import (
    convert_html_tables_to_ascii_with_metadata,
)
from defs.tables.ascii_html.continuation import (
    is_allowed_intervening_content,
)


def test_is_allowed_intervening_content() -> None:
    """Intervening content gate allows page furniture and rejects prose."""
    # Allowed: page breaks and whitespace
    assert (
        is_allowed_intervening_content("<hr/><page>__SEC_PAGE_SPLIT_SENTINEL__") is True
    )
    assert is_allowed_intervening_content("   \n\t  ") is True
    # Allowed: short continuation note
    assert is_allowed_intervening_content("<p>Note 13 (Continued)</p>") is True

    # Rejected: substantial prose narrative
    assert (
        is_allowed_intervening_content(
            "<p>Our primary business model is to purchase multifamily loans for "
            "aggregation and then securitization through issuance of certificates.</p>"
        )
        is False
    )


def test_exhibit_index_two_page_continuation() -> None:
    """Two-page exhibit index tables with matching headers fuse into a single continuous table."""
    html = """
    <div>
        <table>
            <tr><th>Exhibit</th><th>Description</th></tr>
            <tr><td>3.1</td><td>Articles of Incorporation</td></tr>
            <tr><td>3.2</td><td>Bylaws</td></tr>
        </table>
        <hr/>
        <table>
            <tr><th>Exhibit</th><th>Description</th></tr>
            <tr><td>4.1</td><td>Form of Indenture</td></tr>
            <tr><td>4.2</td><td>Form of Note</td></tr>
        </table>
    </div>
    """
    rendered, geometries = convert_html_tables_to_ascii_with_metadata(html)
    assert len(geometries) == 1
    assert "Articles of Incorporation" in rendered
    assert "Form of Note" in rendered
    # Header should only appear once
    assert rendered.count("Exhibit") == 1
    assert rendered.count("Description") == 1


def test_three_page_transitive_table_continuation() -> None:
    """Three-page tables fuse transitively across consecutive page breaks."""
    html = """
    <div>
        <table>
            <tr><th>Item</th><th>2018</th><th>2017</th></tr>
            <tr><td>Cash</td><td>$100</td><td>$90</td></tr>
        </table>
        <hr/>
        <table>
            <tr><th>Item</th><th>2018</th><th>2017</th></tr>
            <tr><td>Investments</td><td>$200</td><td>$180</td></tr>
        </table>
        <hr/>
        <table>
            <tr><th>Item</th><th>2018</th><th>2017</th></tr>
            <tr><td>Equipment</td><td>$300</td><td>$270</td></tr>
        </table>
    </div>
    """
    rendered, geometries = convert_html_tables_to_ascii_with_metadata(html)
    assert len(geometries) == 1
    assert "Cash" in rendered
    assert "Investments" in rendered
    assert "Equipment" in rendered
    assert rendered.count("2018") == 1


def test_table_continuation_with_annotated_header() -> None:
    """Table B with '(Continued)' header fuses with Table A."""
    html = """
    <div>
        <table>
            <tr><th>Category</th><th>Details</th></tr>
            <tr><td>Obligation A</td><td>$500</td></tr>
        </table>
        <hr/>
        <table>
            <tr><th>Category (Continued)</th><th>Details</th></tr>
            <tr><td>Obligation B</td><td>$600</td></tr>
        </table>
    </div>
    """
    rendered, geometries = convert_html_tables_to_ascii_with_metadata(html)
    assert len(geometries) == 1
    assert "Obligation A" in rendered
    assert "Obligation B" in rendered


def test_rejection_of_distinct_tables_with_different_headers() -> None:
    """Adjacent tables with different column headers are not merged."""
    html = """
    <div>
        <table>
            <tr><th>Asset Class</th><th>Fair Value</th></tr>
            <tr><td>Cash Equivalents</td><td>$1,000</td></tr>
        </table>
        <hr/>
        <table>
            <tr><th>Liability Type</th><th>Carrying Value</th></tr>
            <tr><td>Long-Term Debt</td><td>$5,000</td></tr>
        </table>
    </div>
    """
    rendered, geometries = convert_html_tables_to_ascii_with_metadata(html)
    assert len(geometries) == 2
    assert "Asset Class" in rendered
    assert "Liability Type" in rendered


def test_rejection_when_prose_intervenes() -> None:
    """Tables separated by narrative prose are not merged."""
    html = """
    <div>
        <table>
            <tr><th>Exhibit</th><th>Description</th></tr>
            <tr><td>3.1</td><td>Articles of Incorporation</td></tr>
        </table>
        <p>The following additional exhibits are filed herewith or incorporated by reference as indicated below.</p>
        <table>
            <tr><th>Exhibit</th><th>Description</th></tr>
            <tr><td>4.1</td><td>Form of Indenture</td></tr>
        </table>
    </div>
    """
    _rendered, geometries = convert_html_tables_to_ascii_with_metadata(html)
    # The intervening prose is kept and tables remain separate
    assert len(geometries) == 2


def test_rejection_of_headerless_data_tables_with_numeric_amounts() -> None:
    """Headerless data tables containing financial figures are not merged."""
    html = """
    <div>
        <table>
            <tr><td>2013</td><td>$</td><td>9,500</td><td>Firm A</td></tr>
            <tr><td>2012</td><td>$</td><td>13,245</td><td>Firm A</td></tr>
        </table>
        <table>
            <tr><td>2013</td><td>$</td><td>-</td><td>Firm A</td></tr>
            <tr><td>2012</td><td>$</td><td>-</td><td>Firm A</td></tr>
        </table>
    </div>
    """
    _rendered, geometries = convert_html_tables_to_ascii_with_metadata(html)
    # Data tables without structural headers must remain distinct
    assert len(geometries) == 2
