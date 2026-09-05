"""Contract tests for table taxonomy components, shapes, and multi-zone BoW classification."""

from __future__ import annotations

from defs.sec_forms.context.models import (
    RepairPolicy,
    SectionContext,
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


def test_shares_purchased_classification() -> None:
    """Microsoft Table 0009 raw grid with spacer columns is classified structurally."""
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


def test_multi_classification_tags_and_all_matches() -> None:
    """Multi-family matching populates primary family, secondary tags, and all_matches."""
    # A grid with terms matching both fair value hierarchy and pension/benefit obligation
    grid = [
        ["Fair Value Measurement & Obligation", "Level 1", "Level 2", "Total"],
        ["Quoted prices in active markets", "$100", "$200", "$300"],
        ["Observable inputs and unobservable inputs", "$50", "$150", "$200"],
        ["Benefit obligation at beginning of year", "$500", "$600", "$1,100"],
        ["Service cost and interest cost", "$40", "$50", "$90"],
        ["Actuarial loss and benefits paid", "$10", "$20", "$30"],
        ["Benefit obligation at end of year", "$550", "$670", "$1,220"],
    ]
    res = classify_table(grid)
    assert res.family == "fair_value"
    assert len(res.all_matches) >= 2
    matched_families = {m.family for m in res.all_matches}
    assert "fair_value" in matched_families
    assert "pension" in matched_families
    # Primary family is first in all_matches (fair_value has priority 80 > pension priority 0)
    assert res.family == res.all_matches[0].family
    # Secondary matches become tags
    assert "pension" in res.tags
    assert len(res.tags) == len(res.all_matches) - 1
    assert set(res.tags) == matched_families - {res.family}
    for match in res.all_matches:
        assert match.structural_confirmed is True
        assert match.confidence > 0
        assert len(match.evidence) >= 2  # header & body zones


def test_labor_contracts_classification() -> None:
    """Airline/transport collective bargaining table matches labor_contracts."""
    grid = [
        [
            "Employee Group",
            "Bargaining Representative",
            "Number Represented",
            "Contract Amendable Date",
        ],
        ["Pilots", "Air Line Pilots Association (ALPA)", "15,200", "Dec 2026"],
        [
            "Flight Attendants",
            "Association of Flight Attendants (AFA)",
            "28,000",
            "Passed Amendable",
        ],
        [
            "Mechanics & Related",
            "Teamsters / Machinists (IBT/IAM)",
            "12,500",
            "March 2025",
        ],
        ["Dispatchers", "Transport Workers Union (TWU)", "450", "Oct 2027"],
    ]
    res = classify_table(grid)
    assert res.family == "labor_contracts"
    assert res.structural_confirmed is True
    assert res.repair_policy is RepairPolicy.SAFE_GRID_REPAIR


def test_labor_contracts_credit_union_veto() -> None:
    """Financial services credit union references are vetoed from labor_contracts."""
    grid = [
        ["Institution Name", "State", "Total Deposits", "Members"],
        ["First State Credit Union", "CA", "$1,200,000", "45,000"],
        ["Federal Employees Credit Union", "DC", "$5,000,000", "120,000"],
        ["Total Credit Union Deposits", "", "$6,200,000", "165,000"],
    ]
    res = classify_table(grid)
    assert res.family != "labor_contracts"


def test_inventory_classification() -> None:
    """ASC 330 inventory disaggregation by stage and valuation reserve matches inventory."""
    grid = [
        ["(in thousands)", "December 31, 2024", "December 31, 2023"],
        ["Raw materials", "$ 124,500", "$ 115,200"],
        ["Work in process", "45,200", "41,800"],
        ["Finished goods", "210,400", "195,000"],
        ["Gross inventories", "380,100", "352,000"],
        ["LIFO reserve", "(18,500)", "(16,200)"],
        ["Total inventories", "$ 361,600", "$ 335,800"],
    ]
    res = classify_table(grid)
    assert res.family == "inventory"
    assert res.structural_confirmed is True


def test_ppe_classification() -> None:
    """ASC 360 property, plant, and equipment disaggregation matches ppe."""
    grid = [
        ["(in millions)", "2024", "2023"],
        ["Land and improvements", "$ 450", "$ 420"],
        ["Buildings and improvements", "2,150", "1,980"],
        ["Machinery and equipment", "4,320", "3,850"],
        ["Construction in progress", "680", "510"],
        ["Property, plant and equipment, gross", "7,600", "6,760"],
        ["Accumulated depreciation", "(3,100)", "(2,750)"],
        ["Property, plant and equipment, net", "$ 4,500", "$ 4,010"],
    ]
    res = classify_table(grid)
    assert res.family == "ppe"
    assert res.structural_confirmed is True


def test_intangibles_classification() -> None:
    """ASC 350 goodwill and intangible assets breakdown matches intangibles."""
    grid = [
        [
            "Intangible Asset Class",
            "Gross Carrying Amount",
            "Accumulated Amortization",
            "Net",
        ],
        ["Customer relationships", "$ 500,000", "$ (150,000)", "$ 350,000"],
        ["Developed technology", "320,000", "(80,000)", "240,000"],
        ["Trademarks and trade names", "150,000", "(30,000)", "120,000"],
        ["Total intangible assets", "$ 970,000", "$ (260,000)", "$ 710,000"],
    ]
    res = classify_table(grid)
    assert res.family == "intangibles"
    assert res.structural_confirmed is True


def test_derivatives_hedging_classification() -> None:
    """Dedicated ASC 815 derivative table matches derivatives_hedging."""
    grid = [
        [
            "Derivative Category",
            "Notional Amount",
            "Derivative Assets Fair Value",
            "Derivative Liabilities Fair Value",
        ],
        [
            "Derivatives designated as hedging instruments:",
            "",
            "",
            "",
        ],
        ["Interest rate swaps", "$ 1,500,000", "$ 12,400", "$ (3,100)"],
        ["Foreign currency forward contracts", "850,000", "8,200", "(4,500)"],
        [
            "Commodity contracts designated as cash flow hedges",
            "200,000",
            "1,800",
            "(900)",
        ],
        [
            "Total derivatives designated as hedging instruments",
            "$ 2,550,000",
            "$ 22,400",
            "$ (8,500)",
        ],
        [
            "Derivatives not designated as hedging instruments:",
            "",
            "",
            "",
        ],
        ["Foreign exchange options", "$ 300,000", "$ 2,100", "$ (1,200)"],
        ["Total derivative instruments", "$ 2,850,000", "$ 24,500", "$ (9,700)"],
    ]
    res = classify_table(grid)
    assert res.family == "derivatives_hedging"
    assert res.structural_confirmed is True


def test_derivatives_hedging_false_positive_guards() -> None:
    """Physical supply, medical derivatives, shareholder litigation, and stock options are vetoed."""
    # 1. Physical commercial energy supply / NPNS
    physical_grid = [
        ["Contract Type", "Delivery Year", "Volume MMBtu", "Fixed Price"],
        ["Natural gas delivery", "2025", "10,000,000", "$ 3.50"],
        ["Power purchase agreement", "2026", "5,000,000", "$ 45.00"],
        ["Normal purchases and normal sales", "2027", "2,000,000", "$ 3.20"],
    ]
    res_physical = classify_table(physical_grid)
    assert res_physical.family != "derivatives_hedging"

    # 2. Chemical / Medical derivatives
    chemical_grid = [
        ["Product Line", "Volume Tons", "Revenue"],
        ["Cellulose derivatives", "150,000", "$ 450,000"],
        ["Chemical derivatives", "80,000", "220,000"],
        ["Polymer derivatives", "60,000", "180,000"],
    ]
    res_chem = classify_table(chemical_grid)
    assert res_chem.family != "derivatives_hedging"

    # 3. Shareholder derivative litigation
    legal_grid = [
        ["Matter", "Court", "Filing Date", "Status"],
        ["Shareholder derivative lawsuit", "Delaware Chancery", "Jan 2024", "Pending"],
        ["Securities litigation class action", "SDNY", "Mar 2024", "Motion to dismiss"],
        [
            "Derivative action settlement",
            "NDCA",
            "May 2024",
            "Dismissed with prejudice",
        ],
    ]
    res_legal = classify_table(legal_grid)
    assert res_legal.family != "derivatives_hedging"


def test_aoci_rollforward_classification() -> None:
    """ASC 220 Accumulated Other Comprehensive Income rollforward matches aoci."""
    grid = [
        [
            "(in thousands)",
            "Gains (Losses) on Cash Flow Hedges",
            "Foreign Currency Translation",
            "Pension Adjustments",
            "Total AOCI",
        ],
        ["Beginning balance", "$ 45,000", "$ (12,000)", "$ (8,000)", "$ 25,000"],
        [
            "Other comprehensive income (loss) before reclassifications",
            "15,000",
            "(3,500)",
            "1,200",
            "12,700",
        ],
        [
            "Amounts reclassified from accumulated other comprehensive income",
            "(8,000)",
            "—",
            "800",
            "(7,200)",
        ],
        [
            "Net current-period other comprehensive income",
            "7,000",
            "(3,500)",
            "2,000",
            "5,500",
        ],
        ["Ending balance", "$ 52,000", "$ (15,500)", "$ (6,000)", "$ 30,500"],
    ]
    res = classify_table(grid)
    assert res.family == "aoci"
    assert res.structural_confirmed is True


def test_fair_value_with_secondary_derivatives_tag() -> None:
    """ASC 820 Fair Value table with derivatives maintains fair_value primary and tags derivatives."""
    grid = [
        ["Assets / Liabilities", "Level 1", "Level 2", "Level 3", "Total"],
        ["Quoted prices in active markets", "$ 500", "$ —", "$ —", "$ 500"],
        ["Interest rate swap agreements", "$ —", "$ 120", "$ —", "$ 120"],
        ["Foreign currency forward contracts", "$ —", "$ 85", "$ —", "$ 85"],
        [
            "Commodity contracts designated as cash flow hedges",
            "$ —",
            "$ 45",
            "$ 15",
            "$ 60",
        ],
        ["Total derivative assets", "$ —", "$ 250", "$ 15", "$ 265"],
        ["Total fair value of assets", "$ 500", "$ 250", "$ 15", "$ 765"],
    ]
    res = classify_table(grid)
    assert res.family == "fair_value"
    assert "derivatives_hedging" in res.tags
    matched_families = {m.family for m in res.all_matches}
    assert "fair_value" in matched_families
    assert "derivatives_hedging" in matched_families


def test_commodity_derivatives_classification() -> None:
    """Agricultural, metal, and freight derivative schedules classify as derivatives_hedging."""
    grid = [
        [
            "Commodity Derivative Type",
            "Notional",
            "Fair Value Asset",
            "Fair Value Liability",
        ],
        ["Corn futures and options", "$ 45,000", "$ 1,200", "$ (450)"],
        ["Soybean meal swap contracts", "32,000", "850", "(210)"],
        ["Copper forward contracts", "60,000", "2,100", "(800)"],
        ["Aluminum swap agreements", "28,000", "640", "(150)"],
        ["Freight forward contracts", "15,000", "320", "(90)"],
        ["Total commodity derivative contracts", "$ 180,000", "$ 5,110", "$ (1,700)"],
    ]
    res = classify_table(grid)
    assert res.family == "derivatives_hedging"
    assert res.structural_confirmed is True
