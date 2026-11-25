"""Measure-set kind: the Step 3 forms pass, their priced falses fail."""

from __future__ import annotations

from edgar_sec.engine.tables.ascii_html.model.model import (
    ResolvedGrid,
    TableGeometry,
    TableRenderResult,
)
from edgar_sec.engine.tables.extraction.core.text.context import TableContext
from edgar_sec.engine.tables.extraction.form_tests.form_tests import evaluate_form_tests
from edgar_sec.engine.tables.extraction.core.typed_rows import (
    TypedTable,
    structure_table,
)


def _table(rows: tuple[tuple[str, ...], ...]) -> TypedTable:
    geometry = TableGeometry(
        table_index=0,
        render_result=TableRenderResult(
            ascii_text="",
            resolved_grid=ResolvedGrid(
                rows=rows,
                column_alignments=(),
                column_widths=(),
                header_row_count=0,
            ),
            confidence=1.0,
        ),
    )
    return structure_table(TableContext(geometry=geometry))


def _outcome(table: TypedTable, test_id: str):
    return next(o for o in evaluate_form_tests(table) if o.test_id == test_id)


def test_item_703_form_passes_on_its_filed_measures() -> None:
    table = _table(
        (
            (
                "Period",
                "Total Number of Shares Purchased",
                "Average Price Paid Per Share",
                "Total Number of Shares Purchased as Part of Publicly "
                "Announced Plans or Programs",
                "Maximum Number of Shares that May Yet Be Purchased "
                "Under the Plans or Programs",
            ),
            ("October 1 - 31", "10,000", "$ 5.00", "10,000", "1,000,000"),
        )
    )
    assert _outcome(table, "shares_purchased_measure_set").passed


def test_repurchase_lines_inside_hosts_do_not_pass() -> None:
    equity = _table(
        (
            ("Repurchase of common stock", "(1,000)"),
            ("Balance at December 31", "50,000"),
        )
    )
    assert not _outcome(equity, "shares_purchased_measure_set").passed
    cash_flow = _table((("Repurchases of common stock", "(5,000)"),))
    assert not _outcome(cash_flow, "shares_purchased_measure_set").passed


def test_valuation_assumptions_pass_on_the_input_set() -> None:
    table = _table(
        (
            ("", "2025", "2024"),
            ("Expected volatility", "45 %", "47 %"),
            ("Expected dividend yield", "0 %", "0 %"),
            ("Expected term (in years)", "6.0", "6.1"),
            ("Risk-free interest rate", "4.1 %", "3.9 %"),
        )
    )
    outcome = _outcome(table, "valuation_model_assumptions_measure_set")
    assert outcome.passed


def test_level_3_unobservable_inputs_are_refused() -> None:
    table = _table(
        (
            ("Significant unobservable inputs (Level 3)", ""),
            ("Discount rate", "9 %"),
            ("Volatility", "30 %"),
            ("Interest rate", "5 %"),
        )
    )
    outcome = _outcome(table, "valuation_model_assumptions_measure_set")
    assert not outcome.passed
    assert "refused term present" in outcome.detail


def test_warrant_activity_passes_on_the_warrant_subject() -> None:
    table = _table(
        (
            ("", "Number of Warrants", "Weighted Average Exercise Price"),
            ("Warrants outstanding at beginning of period", "1,000", "$ 2.00"),
            ("Granted", "500", "$ 3.00"),
            ("Exercised", "(100)", "$ 2.50"),
            ("Expired", "(50)", "$ 4.00"),
            ("Warrants outstanding at end of period", "1,350", "$ 2.75"),
        )
    )
    assert _outcome(table, "warrant_activity_rollforward").passed


def test_stock_comp_activity_does_not_pass_the_warrant_test() -> None:
    table = _table(
        (
            ("", "Number of Options", "Weighted Average Exercise Price"),
            ("Options outstanding at beginning of period", "1,000", "$ 2.00"),
            ("Granted", "500", "$ 3.00"),
            ("Exercised", "(100)", "$ 2.50"),
            ("Forfeited", "(50)", "$ 4.00"),
            ("Options outstanding at end of period", "1,350", "$ 2.75"),
        )
    )
    outcome = _outcome(table, "warrant_activity_rollforward")
    assert not outcome.passed
    assert "subject absent" in outcome.detail


def test_warrant_listing_passes_and_plan_tables_do_not() -> None:
    listing = _table(
        (
            (
                "Class of Warrant",
                "Number Outstanding",
                "Exercise Price",
                "Remaining Contractual Life",
            ),
            ("Series A Warrants", "100", "$ 1.00", "3.5 years"),
        )
    )
    assert _outcome(listing, "warrant_outstanding_listing").passed
    plan = _table(
        (
            ("Plan Category", "Number of Securities", "Weighted Average Price"),
            (
                "Equity compensation plans approved by security holders",
                "1,000",
                "$ 5.00",
            ),
        )
    )
    assert not _outcome(plan, "warrant_outstanding_listing").passed


def test_item_703_completing_columns_alone_do_not_pass() -> None:
    table = _table(
        (
            (
                "Period",
                "Total Number of Shares Purchased as Part of Publicly "
                "Announced Plans or Programs",
                "Maximum Number of Shares that May Yet Be Purchased "
                "Under the Plans or Programs",
            ),
            ("October 1 - 31", "10,000", "1,000,000"),
        )
    )
    outcome = _outcome(table, "shares_purchased_measure_set")
    assert not outcome.passed
    assert "required group" in outcome.detail


def test_item_703_variant_phrasings_pass_on_the_pair_plus_one() -> None:
    table = _table(
        (
            (
                "Period",
                "Number of Shares Purchased",
                "Average Price per Share",
                "Maximum Dollar Amount Still Available Under Share Repurchase Plan",
            ),
            ("July 1 - 31, 2024", "—", "$ —", "$ 25,000,000"),
            ("August 1 - 31, 2024", "273,202", "$ 13.35", "$ 21,351,540"),
        )
    )
    assert _outcome(table, "shares_purchased_measure_set").passed


def test_item_703_pair_without_any_completing_column_passes_on_the_pair() -> None:
    table = _table(
        (
            (
                "Period",
                "Total Number of Shares Purchased",
                "Average Price Paid per Share",
            ),
            ("July 1 - 31, 2024", "1,000", "$ 6.03"),
        )
    )
    outcome = _outcome(table, "shares_purchased_measure_set")
    assert outcome.passed
    assert "2 of 4 measure groups present (needs 2)" in outcome.detail


def test_combined_statement_passes_all_three_classes() -> None:
    table = _table(
        (
            ("Total revenues", "1,000"),
            ("Gross profit", "600"),
            ("Income from operations", "200"),
            ("Net income", "150"),
            ("Foreign currency translation adjustments", "10"),
            ("Unrealized gain on investments", "5"),
            ("Comprehensive income", "165"),
        )
    )
    assert _outcome(table, "combined_operations_ci_measure_set").passed


def test_combined_statement_with_no_oci_lines_passes_on_the_core() -> None:
    table = _table(
        (
            ("Operating revenues", "317"),
            ("Total operating expenses", "280"),
            ("Operating income", "37"),
            ("Net income", "18"),
            ("Comprehensive income", "18"),
        )
    )
    assert _outcome(table, "combined_operations_ci_measure_set").passed


def test_standalone_comprehensive_income_is_not_the_combined_form() -> None:
    table = _table(
        (
            ("Net income", "150"),
            ("Other comprehensive income", "15"),
            ("Comprehensive income", "165"),
        )
    )
    assert not _outcome(table, "combined_operations_ci_measure_set").passed


def test_combined_joint_total_form_passes_both_tests() -> None:
    table = _table(
        (
            ("Research and development", "$ 63,104"),
            ("General and administrative", "20,779"),
            ("Total operating expenses", "83,883"),
            ("Loss from operations", "(83,883)"),
            ("Net loss and comprehensive loss", "$ (75,801)"),
        )
    )
    assert _outcome(table, "combined_operations_ci_joint_measure_set").passed
    # The joint line carries the terminus and the comprehensive
    # total in one line, so the core form passes on it too.
    assert _outcome(table, "combined_operations_ci_measure_set").passed


def test_balance_sheet_aoci_lines_are_not_the_combined_form() -> None:
    table = _table(
        (
            ("Cash and cash equivalents", "$ 34,367"),
            ("Deferred revenue", "4,056"),
            ("Total assets", "$ 203,489"),
            ("Accumulated other comprehensive income (loss)", "(1,200)"),
            ("Total liabilities and stockholders' equity", "$ 203,489"),
        )
    )
    assert not _outcome(table, "combined_operations_ci_measure_set").passed
    assert not _outcome(table, "combined_operations_ci_joint_measure_set").passed


def test_income_statement_alone_is_not_the_combined_form() -> None:
    table = _table(
        (
            ("Total revenues", "1,000"),
            ("Gross profit", "600"),
            ("Net income", "150"),
        )
    )
    assert not _outcome(table, "combined_operations_ci_measure_set").passed


def test_goodwill_standard_walk_passes() -> None:
    table = _table(
        (
            ("Goodwill",),
            ("2003", "2002", "2001"),
            ("Balance at beginning of year", "14,706,191", "9,174,934"),
            ("Additional purchase price allocation", "100", "50"),
            ("Goodwill arising from business acquisitions", "200", "150"),
            ("Amortization expense", "(10)", "(10)"),
            ("Balance at end of year", "14,906,191", "9,324,934"),
        )
    )
    assert _outcome(table, "goodwill_rollforward_measure_set").passed


def test_goodwill_dated_stubs_pass() -> None:
    table = _table(
        (
            ("Goodwill:",),
            ("Printing", "Office Products and Furniture", "Newspaper", "Total"),
            ("Balance as of October 31, 2008", "100", "200", "300", "600"),
            ("Goodwill acquired Fiscal 2009", "10", "20", "30", "60"),
            ("Impairment losses Fiscal 2009", "(5)", "(5)", "(5)", "(15)"),
            ("Balance at October 31, 2009", "105", "215", "325", "645"),
        )
    )
    assert _outcome(table, "goodwill_rollforward_measure_set").passed


def test_goodwill_transposed_bare_date_headers_pass() -> None:
    table = _table(
        (
            (
                "The changes in the gross carrying amount and "
                "accumulated impairment loss are as follows:",
            ),
            (
                "Adjustments to Goodwill",
                "December 29, 2012",
                "Acquisitions",
                "Foreign Exchange",
                "December 28, 2013",
            ),
            ("Research Models and Services", "", "", "", ""),
            ("Gross carrying amount", "100", "10", "1", "111"),
        )
    )
    assert _outcome(table, "goodwill_rollforward_measure_set").passed


def test_goodwill_as_of_stubs_pass() -> None:
    table = _table(
        (
            (
                "Changes in the carrying amount of the Company’s "
                "goodwill for the year ended December 31, 2007 were "
                "as follows (in thousands):",
            ),
            ("", "Amount"),
            ("As of January 1, 2006", "12,388"),
            ("Goodwill acquired in 2006:", "100"),
            ("Purchase price adjustments", "10"),
            ("As of December 31, 2006", "12,498"),
        )
    )
    assert _outcome(table, "goodwill_rollforward_measure_set").passed


def test_goodwill_brought_carried_forward_passes() -> None:
    table = _table(
        (
            ("Notes",),
            ("NOTE 8 GOODWILL* (Kronas in thousands)", "12/31/2015", "12/31/2014"),
            ("- Acquisition value brought forward", "100", "90"),
            ("- Amortization brought forward", "(10)", "(9)"),
            ("Accumulated acquisition value carried forward", "90", "81"),
        )
    )
    assert _outcome(table, "goodwill_rollforward_measure_set").passed


def test_goodwill_activity_movement_passes() -> None:
    table = _table(
        (
            (
                "Changes in goodwill for the years ended September 30, "
                "2003 and 2004 are as follows (in thousands):",
            ),
            ("Balance as of September 30, 2002", "68,812"),
            ("Goodwill activity during year", "100"),
            ("Balance as of September 30, 2003", "68,912"),
        )
    )
    assert _outcome(table, "goodwill_rollforward_measure_set").passed


def test_goodwill_foreign_currency_only_movement_passes() -> None:
    table = _table(
        (
            ("Goodwill",),
            ("", "Domestic", "Canada", "Total"),
            ("Balance at September 26, 2015", "423,958", "323,448", "747,406"),
            ("Foreign currency effect", "(1,073)", "(11,342)", "(12,415)"),
            ("Balance at December 26, 2015", "422,885", "312,106", "734,991"),
        )
    )
    assert _outcome(table, "goodwill_rollforward_measure_set").passed


def test_goodwill_sale_of_operations_movement_passes() -> None:
    table = _table(
        (
            ("Goodwill",),
            ("", "Paperboard", "Fiber", "Total"),
            ("Balance as of December 31, 2005", "68,396", "3,777", "129,275"),
            ("Sale of partition operations", "—", "—", "(1,701)"),
            ("Balance as of June 30, 2006", "68,396", "3,777", "127,574"),
        )
    )
    assert _outcome(table, "goodwill_rollforward_measure_set").passed


def test_goodwill_single_ended_chain_passes() -> None:
    table = _table(
        (
            ("Goodwill",),
            ("Ending balance, December 31, 2008", "315,018"),
            ("Purchase price adjustment for acquisitions", "10,811"),
            ("Preliminary estimated impairment loss", "(184,000)"),
            ("Ending balance, March 31, 2009", "41,334"),
        )
    )
    assert _outcome(table, "goodwill_rollforward_measure_set").passed


def test_goodwill_movements_without_an_ending_bookend_are_refused() -> None:
    table = _table(
        (
            ("Goodwill",),
            ("Goodwill acquired during the year", "100"),
            ("Impairment losses", "(10)"),
            ("Purchase price adjustments", "5"),
        )
    )
    assert not _outcome(table, "goodwill_rollforward_measure_set").passed


def test_equity_machine_without_goodwill_is_refused() -> None:
    table = _table(
        (
            ("(In thousands of United States dollars, except number of shares)",),
            ("Balance at December 31, 2003, as restated", "100"),
            ("Issuance of common stock for acquisition of subsidiaries", "10"),
            ("Foreign currency translation gain", "5"),
            ("Balance at December 31, 2004", "115"),
        )
    )
    outcome = _outcome(table, "goodwill_rollforward_measure_set")
    assert not outcome.passed
    assert "subject absent" in outcome.detail


def test_intangibles_fragment_is_refused() -> None:
    table = _table(
        (
            (
                "Changes in the carrying amount of the Company’s "
                "intangible and other assets for the years ended "
                "December 31, 2007 and 2006 were as follows "
                "(in thousands):",
            ),
            ("As of January 1, 2006, net", "1,133"),
            ("Intangible assets acquired in 2006:", "100"),
            ("Amortization expense", "(50)"),
            ("As of December 31, 2006", "1,183"),
            ("Reclassification from goodwill—2006 acquisitions (Note 6)", "(10)"),
            ("As of December 31, 2007", "1,173"),
        )
    )
    outcome = _outcome(table, "goodwill_rollforward_measure_set")
    assert not outcome.passed
    assert "subject not in walk position" in outcome.detail


def test_static_two_date_carrying_is_refused() -> None:
    table = _table(
        (
            (
                "As of December 31, 2021, the goodwill balances "
                "remaining for each of our reporting units were "
                "as follows:",
            ),
            (
                "Goodwill at December 31, 2021",
                "Goodwill at December 31, 2020",
                "Reporting Unit:",
            ),
            ("Local Advertising", "100", "90"),
            ("National Digital", "50", "45"),
            ("Balance", "150", "135"),
        )
    )
    assert not _outcome(table, "goodwill_rollforward_measure_set").passed


def test_single_bookend_fragment_is_refused() -> None:
    table = _table(
        (
            ("The following table summarizes the changes in goodwill by segment:",),
            ("Goodwill acquired during the period", "10"),
            ("Goodwill retired during the period", "(2)"),
            ("Balance at end of period", "108"),
        )
    )
    outcome = _outcome(table, "goodwill_rollforward_measure_set")
    assert not outcome.passed
    assert "2 of 6 measure groups present" in outcome.detail


def test_composition_without_bookends_is_refused() -> None:
    table = _table(
        (
            ("The table below sets forth the carrying amount of goodwill:",),
            ("Gross carrying amount", "100"),
            ("Accumulated impairment", "(10)"),
            ("Goodwill, net", "90"),
        )
    )
    assert not _outcome(table, "goodwill_rollforward_measure_set").passed


def test_goodwill_definite_article_anchors_pass() -> None:
    table = _table(
        (
            ("USG Boral Building Products Pty Limited and Controlled Entities",),
            ("Reconciliation of movements in goodwill", ""),
            ("Balance at the beginning of the year", "100"),
            ("Acquisition of entities or operations", "10"),
            ("Write off of goodwill", "(5)"),
            ("Net foreign currency exchange differences", "1"),
            ("Balance at the end of the year", "106"),
        )
    )
    assert _outcome(table, "goodwill_rollforward_measure_set").passed


def test_goodwill_gross_leg_stubs_pass() -> None:
    table = _table(
        (
            (
                "The changes in the carrying amount of goodwill are "
                "as follows (in thousands):",
            ),
            ("Goodwill (gross) at December 31, 2010", "179,286"),
            ("Acquired goodwill", "137"),
            ("Goodwill (gross) at December 31, 2011", "179,423"),
        )
    )
    assert _outcome(table, "goodwill_rollforward_measure_set").passed


def test_goodwill_trailing_qualifier_stubs_pass() -> None:
    table = _table(
        (
            (
                "The following table shows changes in the carrying "
                "amount of goodwill for the 2016, 2015 Successor and "
                "2015 Predecessor periods (in thousands):",
            ),
            ("Balance at January 31, 2015 (Predecessor)", "67,413"),
            ("Goodwill recognized as part of the Acquisition", "200"),
            ("Balance at January 30, 2016 (Successor)", "67,613"),
        )
    )
    assert _outcome(table, "goodwill_rollforward_measure_set").passed


def test_goodwill_month_day_stubs_pass() -> None:
    table = _table(
        (
            (
                "The changes in the carrying amount of goodwill for "
                "the years ended September 30, 2012 and 2011 are "
                "as follows:",
            ),
            ("Balance as of October 1:", "100"),
            ("Foreign currency translation", "5"),
            ("Balance as of September 30", "105"),
        )
    )
    assert _outcome(table, "goodwill_rollforward_measure_set").passed


def test_goodwill_day_first_stubs_pass() -> None:
    table = _table(
        (
            ("11 Goodwill",),
            ("At 31 December 2003", "100"),
            ("Impairment charge", "(5)"),
            ("At 31 December 2004", "95"),
        )
    )
    assert _outcome(table, "goodwill_rollforward_measure_set").passed


def test_dated_header_composition_is_refused() -> None:
    table = _table(
        (
            (
                "The table below set forth the carrying amount of "
                "goodwill for the year ended December 31, 2023 "
                "and 2022:",
            ),
            ("As of December 31, 2023", "As of December 31, 2022"),
            ("Gross carrying amount", "100"),
            ("Acquired in business combination (1)", "10"),
            ("Accumulated impairment", "(5)"),
            ("Goodwill, net", "105"),
        )
    )
    assert not _outcome(table, "goodwill_rollforward_measure_set").passed


def test_valuation_allowance_host_walk_is_refused() -> None:
    table = _table(
        (
            ("The components of the net deferred tax assets are as follows:",),
            ("In Thousands", "2010", "2009"),
            ("Goodwill and intangible assets", "100", "90"),
            ("Valuation Allowance", "", ""),
            ("Beginning balance", "50", "45"),
            ("Increase (decrease) during period", "5", "5"),
            ("Ending balance", "55", "50"),
        )
    )
    outcome = _outcome(table, "goodwill_rollforward_measure_set")
    assert not outcome.passed
    assert "subject not in walk position" in outcome.detail


def test_cash_walk_is_refused() -> None:
    table = _table(
        (
            ("CONSOLIDATED STATEMENTS OF CASH FLOWS",),
            ("For the Year Ended December 31,", "2023", "2022"),
            ("Impairment on goodwill", "(5)", "(3)"),
            ("Acquisition of subsidiaries, net cash acquired", "(100)", "(80)"),
            ("CASH AND CASH EQUIVALENTS, BEGINNING OF YEAR", "500", "450"),
            ("CASH AND CASH EQUIVALENTS, END OF YEAR", "395", "500"),
        )
    )
    outcome = _outcome(table, "goodwill_rollforward_measure_set")
    assert not outcome.passed
    assert "subject not in walk position" in outcome.detail


def _prose_table(rows: tuple[tuple[str, ...], ...], prose_before: str) -> TypedTable:
    geometry = TableGeometry(
        table_index=0,
        render_result=TableRenderResult(
            ascii_text="",
            resolved_grid=ResolvedGrid(
                rows=rows,
                column_alignments=(),
                column_widths=(),
                header_row_count=0,
            ),
            confidence=1.0,
        ),
    )
    context = TableContext(geometry=geometry, prose_before=prose_before)
    return structure_table(context)


def test_goodwill_subject_carried_by_lead_in_prose_passes() -> None:
    rows = (
        ("Printing", "Office Products", "Total"),
        ("Balance as of October 31, 2008", "100", "200", "300"),
        ("Acquisitions", "10", "20", "30"),
        ("Impairment losses", "(5)", "(5)", "(10)"),
        ("Balance as of October 31, 2009", "105", "215", "320"),
    )
    prose = "The following table summarizes the changes in goodwill."
    assert _outcome(
        _prose_table(rows, prose), "goodwill_rollforward_measure_set"
    ).passed
    silent = "The following table summarizes the changes in carrying amount."
    outcome = _outcome(_prose_table(rows, silent), "goodwill_rollforward_measure_set")
    assert not outcome.passed
    assert "subject absent" in outcome.detail


def test_goodwill_prose_clears_the_walk_position_binding() -> None:
    rows = (
        ("Balance at beginning of year", "100"),
        ("Goodwill acquired", "10"),
        ("Impairment", "(5)"),
        ("Balance at end of year", "105"),
    )
    outcome = _outcome(_prose_table(rows, ""), "goodwill_rollforward_measure_set")
    assert not outcome.passed
    assert "subject not in walk position" in outcome.detail
    prose = "Goodwill activity for the year ended December 31 was as follows."
    assert _outcome(
        _prose_table(rows, prose), "goodwill_rollforward_measure_set"
    ).passed


def test_goodwill_net_carrying_value_bookends_pass() -> None:
    table = _table(
        (
            ("Goodwill",),
            ("Net carrying value as of December 31, 2024", "100"),
            ("Acquisitions", "10"),
            ("Impairment losses", "(5)"),
            ("Net carrying value as of December 31, 2025", "105"),
        )
    )
    assert _outcome(table, "goodwill_rollforward_measure_set").passed


def test_goodwill_additions_only_movement_passes() -> None:
    table = _table(
        (
            ("Goodwill",),
            ("Balance at beginning of year", "100"),
            ("Additions", "0"),
            ("Balance at end of year", "100"),
        )
    )
    assert _outcome(table, "goodwill_rollforward_measure_set").passed


def test_item_703_pair_only_summary_passes_on_the_pair() -> None:
    table = _table(
        (
            (
                "Period",
                "Number of Shares Repurchased",
                "Average Price Per Share",
                "Amount",
            ),
            ("January 2023", "1,000", "10.00", "10,000"),
        )
    )
    assert _outcome(table, "shares_purchased_measure_set").passed


def test_item_703_variant_program_phrasings_pass() -> None:
    table = _table(
        (
            (
                "Total Number of Shares Purchased",
                "Weighted-Average Per Share Price",
                "Cumulative Shares Repurchased Under the Program",
                "Dollar Amount Remaining Under The Program",
            ),
            ("1,000", "10.00", "1,000", "5,000"),
        )
    )
    assert _outcome(table, "shares_purchased_measure_set").passed


def test_combined_statement_descent_totals_pass() -> None:
    table = _table(
        (
            ("Total revenues", "100"),
            ("Total expenses", "80"),
            ("Net income", "20"),
            ("Other comprehensive income", "3"),
            ("Comprehensive income", "23"),
        )
    )
    assert _outcome(table, "combined_operations_ci_measure_set").passed


def test_combined_statement_translation_adjustment_passes() -> None:
    table = _table(
        (
            ("Operating income", "20"),
            ("Net income", "20"),
            ("Cumulative translation adjustment", "3"),
            ("Comprehensive income", "23"),
        )
    )
    assert _outcome(table, "combined_operations_ci_measure_set").passed
