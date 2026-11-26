"""Measure-set kind: the goodwill at-size pricing rounds' forms —
the packet-3 coverage forms and the dated recognizer's widened
forms, priced over the family's union population at size."""

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


def test_goodwill_balance_as_at_ending_stub_passes() -> None:
    table = _table(
        (
            ("Goodwill",),
            ("Balance as of January 1, 2008", "11,305"),
            ("Goodwill impairment", "(7,105)"),
            ("Balance as at December 31, 2008", "4,200"),
        )
    )
    assert _outcome(table, "goodwill_rollforward_measure_set").passed


def test_goodwill_goodwill_balance_stubs_pass() -> None:
    table = _table(
        (
            ("Goodwill balance as of December 31, 2022", "100"),
            ("Addition - acquisition of Tagger", "5"),
            ("Goodwill balance as of December 31, 2023", "105"),
        )
    )
    assert _outcome(table, "goodwill_rollforward_measure_set").passed


def test_goodwill_balance_dash_chain_passes() -> None:
    table = _table(
        (
            ("Goodwill",),
            ("Balance - October 1, 2011", "8,156"),
            ("Impairment", "—"),
            ("Balance - September 30, 2012", "8,156"),
        )
    )
    assert _outcome(table, "goodwill_rollforward_measure_set").passed


def test_goodwill_balance_as_of_year_end_stubs_pass() -> None:
    table = _table(
        (
            ("Goodwill",),
            ("Balance as of year end 2022", "100"),
            ("Additions due to acquisitions", "5"),
            ("Assets held for sale", "(2)"),
            ("Balance as of year end 2023", "103"),
        )
    )
    assert _outcome(table, "goodwill_rollforward_measure_set").passed


def test_goodwill_net_balance_at_stubs_pass() -> None:
    table = _table(
        (
            ("Goodwill",),
            ("Net balance at June 30, 2015", "100"),
            ("Translation adjustment", "3"),
            ("Net balance at June 30, 2016", "103"),
        )
    )
    assert _outcome(table, "goodwill_rollforward_measure_set").passed


def test_goodwill_retrospectively_adjusted_stub_passes() -> None:
    table = _table(
        (
            ("Goodwill",),
            ("Balances at March 31, 2014, as retrospectively adjusted", "100"),
            ("Acquisitions", "5"),
            ("Disposals", "(2)"),
            ("Balances at March 31, 2016", "103"),
        )
    )
    assert _outcome(table, "goodwill_rollforward_measure_set").passed


def test_goodwill_second_column_movements_pass() -> None:
    table = _table(
        (
            ("Goodwill",),
            ("Balance as of December 31, 2010", "3,140"),
            ("", "Impairment", "-"),
            ("", "Acquisitions", "82"),
            ("", "Dispositions", "(10)"),
            ("Balance as of December 31, 2011", "3,212"),
        )
    )
    assert _outcome(table, "goodwill_rollforward_measure_set").passed


def test_second_column_movements_without_subject_are_refused() -> None:
    table = _table(
        (
            ("Customer relationships", "100"),
            ("", "Acquisitions", "5"),
            ("", "Impairment", "(2)"),
            ("", "Adjustments", "1"),
        )
    )
    assert not _outcome(table, "goodwill_rollforward_measure_set").passed


def test_goodwill_exchange_only_movement_passes() -> None:
    table = _table(
        (
            ("Goodwill",),
            ("", "Amount"),
            ("Balance at December 31, 2015", "100"),
            ("Amortization", "(1)"),
            ("Foreign exchange", "2"),
            ("Balance at June 30, 2016", "101"),
        )
    )
    assert _outcome(table, "goodwill_rollforward_measure_set").passed


def test_goodwill_amortization_only_movement_fails() -> None:
    table = _table(
        (
            ("Goodwill",),
            ("Balance at December 31, 2015", "100"),
            ("Amortization", "(5)"),
            ("Balance at June 30, 2016", "95"),
        )
    )
    assert not _outcome(table, "goodwill_rollforward_measure_set").passed


def test_goodwill_beginning_end_of_the_period_phrases_pass() -> None:
    table = _table(
        (
            ("Goodwill",),
            ("Balance, beginning of the period", "100"),
            ("Business acquisition", "5"),
            ("Balance, end of the period", "105"),
        )
    )
    assert _outcome(table, "goodwill_rollforward_measure_set").passed


def test_goodwill_end_of_the_year_phrase_passes() -> None:
    table = _table(
        (
            ("Goodwill",),
            ("Balance at Beginning of the Year", "100"),
            ("Acquisition", "5"),
            ("Impairment", "(1)"),
            ("Foreign Currency Translations", "1"),
            ("Balance at End of the Year", "105"),
        )
    )
    assert _outcome(table, "goodwill_rollforward_measure_set").passed


def test_goodwill_unspaced_month_day_bookend_passes() -> None:
    table = _table(
        (
            ("Goodwill",),
            ("Net balance as of August 30, 2014", "100"),
            ("Goodwill adjustments added through acquisitions", "5"),
            ("Net balance as of February14, 2015", "105"),
        )
    )
    assert _outcome(table, "goodwill_rollforward_measure_set").passed


def test_goodwill_year_first_year_end_bookends_pass() -> None:
    table = _table(
        (
            ("Goodwill",),
            ("Balance as of 2014 year end", "100"),
            ("Currency translation", "1"),
            ("Acquisition", "5"),
            ("Balance as of 2015 year end", "106"),
        )
    )
    assert _outcome(table, "goodwill_rollforward_measure_set").passed


def test_goodwill_trailing_continuation_bookend_passes() -> None:
    table = _table(
        (
            ("Goodwill",),
            ("Balance as of December 31, 2017", "100"),
            ("Additions", "5"),
            ("Impairment", "(1)"),
            ("Balance as of December 31, 2018 and March 31, 2019", "104"),
        )
    )
    assert _outcome(table, "goodwill_rollforward_measure_set").passed
