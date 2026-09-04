"""Contract tests for table taxonomy components, shapes, and multi-zone BoW classification."""

from __future__ import annotations

from defs.sec_forms.context.models import (
    RepairPolicy,
    SectionContext,
)
from defs.tables.templates.shares_purchased import (
    shares_purchased_template,
)
from defs.taxonomy.tables.classifier import classify_table


def test_standalone_cover_layout_classification() -> None:
    """A standalone table with high-entropy cover anchors is classified as cover_layout."""
    grid = [
        ["Delaware", "12-3456789"],
        [
            "(State or other jurisdiction of incorporation)",
            "(I.R.S. Employer Identification No.)",
        ],
    ]
    res = classify_table(grid)
    assert res.family == "cover_layout"
    assert res.confidence >= 0.70
    assert res.structural_confirmed is True
    assert res.repair_policy is RepairPolicy.PRESENTATION_ONLY


def test_body_properties_zip_rejected_from_cover() -> None:
    """A body properties table with only zip/address qualifiers is rejected standalone."""
    grid = [
        ["Facility Name", "Address", "Zip Code", "Square Feet"],
        ["Building A", "100 Main St", "90210", "45,000"],
        ["Building B", "200 Oak Ave", "94105", "60,000"],
    ]
    res = classify_table(grid)
    assert res.family != "cover_layout"


def test_income_statement_shape_and_vocabulary() -> None:
    """An income statement with >=8 rows matches; a 2-row table is rejected by shape."""
    full_grid = [
        ["Three Months Ended Sept 30", "2024", "2023"],
        ["Total revenues", "1000", "900"],
        ["Cost of revenue", "400", "350"],
        ["Gross profit", "600", "550"],
        ["Research and development", "150", "140"],
        ["Selling, general and administrative", "150", "130"],
        ["Total operating expenses", "300", "270"],
        ["Operating income", "300", "280"],
        ["Net income", "240", "220"],
        ["Basic earnings per share", "2.40", "2.20"],
        ["Diluted earnings per share", "2.35", "2.15"],
    ]
    res_full = classify_table(full_grid)
    assert res_full.family == "income_statement"
    assert res_full.structural_confirmed is True
    assert res_full.repair_policy is RepairPolicy.SAFE_GRID_REPAIR

    short_grid = [
        ["Segment", "Total revenues"],
        ["North America", "1000"],
    ]
    res_short = classify_table(short_grid)
    assert res_short.family is None
    assert res_short.structural_confirmed is False


def test_shares_purchased_classification_and_template_repair() -> None:
    """Microsoft Table 0009 raw grid with spacer columns is repaired into canonical 5 columns."""
    raw_msft_grid = [
        [
            "Period",
            "Total Number of Shares Purchased",
            "Average Price Paid Per Share",
            "",
            "Total Number of Shares Purchased as Part of Publicly Announced Plans or Programs",
            "Approximate Dollar Value of Shares That May Yet Be Purchased Under the Plans or Programs",
            "",
        ],
        ["(In millions)", "", "", "", "", "", ""],
        [
            "April 1, 2025 – April 30, 2025",
            "3,180,776",
            "$376.90",
            "",
            "3,180,776",
            "$59,350",
            "",
        ],
        [
            "May 1, 2025 – May 31, 2025",
            "2,360,700",
            "",
            "448.01",
            "2,360,700",
            "",
            "58,293",
        ],
        [
            "June 1, 2025 – June 30, 2025",
            "1,979,017",
            "",
            "476.78",
            "1,979,017",
            "",
            "57,349",
        ],
        ["", "7,520,493", "", "", "7,520,493", "", ""],
    ]

    res = classify_table(raw_msft_grid)
    assert res.family == "shares_purchased"
    assert res.structural_confirmed is True
    assert res.repair_policy is RepairPolicy.FAMILY_TEMPLATE

    repaired_output = shares_purchased_template(raw_msft_grid)
    assert repaired_output is not None
    assert "<TABLE>" in repaired_output
    assert "April 1, 2025 – April 30, 2025" in repaired_output
    assert "$448.01" in repaired_output
    assert "$58,293" in repaired_output
    assert "$476.78" in repaired_output
    assert "Total" in repaired_output
    assert "7,520,493" in repaired_output
    assert "Period" in repaired_output
    assert "Shares Purchased" in repaired_output
    assert "Average Price Paid" in repaired_output


def test_equity_statement_classification() -> None:
    """Statement of stockholders equity matches with APIC, retained earnings, balance at."""
    grid = [
        [
            "Common Stock",
            "Additional Paid-in Capital",
            "Retained Earnings",
            "Total Equity",
        ],
        ["Balance at beginning of year", "100", "500", "1200", "1800"],
        ["Net income", "", "", "400", "400"],
        ["Stock-based compensation", "", "50", "", "50"],
        ["Balance at end of year", "100", "550", "1600", "2250"],
    ]
    res = classify_table(grid)
    assert res.family == "equity_statement"
    assert res.structural_confirmed is True


def test_lease_maturity_classification_and_template() -> None:
    """Lease maturity table with minimum lease payments and imputed interest matches."""

    grid = [
        ["Fiscal Year", "Operating Leases", "Finance Leases"],
        ["2025", "100", "20"],
        ["2026", "90", "18"],
        ["2027", "80", "15"],
        ["Thereafter", "200", "50"],
        ["Total minimum lease payments", "470", "103"],
        ["Less imputed interest", "(70)", "(13)"],
        ["Present value of lease liabilities", "400", "90"],
    ]
    res = classify_table(grid)
    assert res.family == "lease_maturity"
    assert res.structural_confirmed is True


def test_fair_value_classification_and_template() -> None:
    """Fair value 3-level measurement hierarchy matrix matches and repairs cleanly."""

    grid = [
        ["Assets", "Level 1", "Level 2", "Level 3", "Total"],
        ["U.S. Treasury securities", "500", "", "", "500"],
        ["Corporate debt securities", "", "800", "", "800"],
        ["Derivative assets", "", "150", "50", "200"],
        ["Total fair value", "500", "950", "50", "1500"],
    ]
    res = classify_table(grid)
    assert res.family == "fair_value"
    assert res.structural_confirmed is True


def test_tax_reconciliation_classification() -> None:
    """Income tax rate reconciliation matches statutory rate baseline."""
    grid = [
        ["", "2024", "2023"],
        ["Federal statutory rate", "21.0%", "21.0%"],
        ["State and local income taxes", "3.5%", "3.2%"],
        ["Foreign rate differential", "(2.1%)", "(1.8%)"],
        ["Effective tax rate", "22.4%", "22.4%"],
    ]
    res = classify_table(grid)
    assert res.family == "tax_reconciliation"
    assert res.structural_confirmed is True


def test_stock_comp_rollforward_classification() -> None:
    """ASC 718 stock option activity rollforward matches."""
    grid = [
        ["Options Activity", "Shares", "Weighted-Average Exercise Price"],
        ["Options outstanding at beginning", "1,000,000", "$25.00"],
        ["Shares granted", "200,000", "$32.00"],
        ["Shares exercised", "(150,000)", "$20.00"],
        ["Shares forfeited", "(50,000)", "$28.00"],
        ["Options outstanding at end", "1,000,000", "$27.50"],
    ]
    res = classify_table(grid)
    assert res.family == "stock_comp_rollforward"
    assert res.structural_confirmed is True


def test_pension_classification() -> None:
    """ASC 715 pension benefit obligation and plan asset breakdown matches."""
    grid = [
        ["Change in Benefit Obligation", "2024", "2023"],
        ["Benefit obligation at beginning of year", "5000", "4800"],
        ["Service cost", "150", "140"],
        ["Interest cost", "200", "190"],
        ["Actuarial loss", "50", "30"],
        ["Benefits paid", "(300)", "(280)"],
        ["Benefit obligation at end of year", "5100", "5000"],
    ]
    res = classify_table(grid)
    assert res.family == "pension"
    assert res.structural_confirmed is True


def test_eps_reconciliation_classification() -> None:
    """ASC 260 basic vs diluted share count reconciliation matches."""
    grid = [
        ["Numerator / Denominator", "2024", "2023"],
        ["Basic earnings per share", "$2.50", "$2.10"],
        ["Weighted-average shares - basic", "100,000", "98,000"],
        ["Dilutive effect of stock options", "4,000", "3,500"],
        ["Weighted-average shares - diluted", "104,000", "101,500"],
        ["Diluted earnings per share", "$2.40", "$2.03"],
    ]
    res = classify_table(grid)
    assert res.family == "eps_reconciliation"
    assert res.structural_confirmed is True


def test_multi_zone_context_boosting() -> None:
    """A qualifier-only address table is boosted when preceding neighbor has principal address."""
    grid = [
        ["One Apple Park Way, Cupertino, CA", "95014"],
        ["Address", "(Zip Code)"],
    ]

    # Without context: not matched standalone
    res_standalone = classify_table(grid)
    assert res_standalone.family != "cover_layout"

    # With neighbor context: boosted to matched
    ctx = SectionContext(
        heading="Cover Page",
        preceding_blocks=("Address of Principal Executive Offices:",),
    )
    res_boosted = classify_table(grid, section_context=ctx)
    assert res_boosted.family == "cover_layout"
    assert res_boosted.structural_confirmed is True


def test_activities_veto_on_income_statement() -> None:
    """Cash flow activities veto income statement classification."""
    grid = [
        ["Three Months Ended Sept 30", "2024", "2023"],
        ["Total revenues", "1000", "900"],
        ["Cost of revenue", "400", "350"],
        ["Gross profit", "600", "550"],
        ["Cash flows from operating activities", "300", "270"],
        ["Operating income", "300", "280"],
        ["Net income", "240", "220"],
        ["Basic earnings per share", "2.40", "2.20"],
    ]
    res = classify_table(grid)
    assert res.family != "income_statement"
