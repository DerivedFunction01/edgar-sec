"""Year-ladder form test: registry data and specimen-shaped grids."""

from __future__ import annotations

from edgar_sec.engine.tables.ascii_html.model.model import (
    ResolvedGrid,
    TableGeometry,
    TableRenderResult,
)
from edgar_sec.engine.tables.extraction.core.text.context import TableContext
from edgar_sec.engine.tables.extraction.form_specs.form_test_specs import (
    FORM_TEST_SPECS,
    LADDER_SPECS_BY_TEST_ID,
    form_test_specs_for,
)
from edgar_sec.engine.tables.extraction.form_specs.year_ladder_specs import (
    YEAR_LADDER_SPECS,
)
from edgar_sec.engine.tables.extraction.core.subjects.profile_constants import (
    TEST_LADDER,
)
from edgar_sec.engine.tables.extraction.core.subjects.profiles import (
    PROFILES_BY_FAMILY,
)
from edgar_sec.engine.tables.extraction.core.typed_rows import structure_table
from edgar_sec.engine.tables.extraction.form_tests.year_ladder import (
    _asof_year,
    _step_for_label,
    evaluate_form_test_ladder,
    evaluate_year_ladder,
)

DEBT = LADDER_SPECS_BY_TEST_ID["debt_maturity_year_ladder"]
COMMITMENTS = LADDER_SPECS_BY_TEST_ID["commitments_contingencies_year_ladder"]


def _context(rows: tuple[tuple[str, ...], ...]) -> TableContext:
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
    return TableContext(geometry=geometry)


DEBT_COLUMNS = _context(
    (
        ("", "2026", "2027", "2028", "2029", "2030", "Thereafter", "Total"),
        ("Long-term debt", "100", "200", "300", "400", "500", "600", "2,100"),
        ("Notes payable", "10", "20", "30", "40", "50", "60", "210"),
    )
)
PAYMENTS_DUE = _context(
    (
        (
            "",
            "Total",
            "Less than 1 year",
            "1 to 3 years",
            "3 to 5 years",
            "More than 5 years",
        ),
        ("Purchase obligations", "1,000", "400", "300", "200", "100"),
        ("Operating leases", "500", "200", "150", "100", "50"),
    )
)


def test_ladder_specs_are_registry_data_on_the_two_families() -> None:
    assert TEST_LADDER in PROFILES_BY_FAMILY["debt_maturity"].form_tests
    assert TEST_LADDER in PROFILES_BY_FAMILY["commitments_contingencies"].form_tests
    assert DEBT.min_year_steps == 4 and DEBT.bucket_ladder is False
    assert COMMITMENTS.min_year_steps == 3 and COMMITMENTS.bucket_ladder is True
    assert COMMITMENTS.min_bucket_steps == 3
    declared = {
        spec.test_id: spec for spec in FORM_TEST_SPECS if spec.kind == TEST_LADDER
    }
    assert set(declared) == set(LADDER_SPECS_BY_TEST_ID)
    for test_id, spec in declared.items():
        assert YEAR_LADDER_SPECS[spec.family] is LADDER_SPECS_BY_TEST_ID[test_id]
    assert set(YEAR_LADDER_SPECS) == {"debt_maturity", "commitments_contingencies"}
    assert not hasattr(PROFILES_BY_FAMILY["debt_maturity"], "ladder_spec")
    for test_id, spec in declared.items():
        assert spec.kind == TEST_LADDER and spec.points == 3.0
        family_ladder = tuple(
            s for s in form_test_specs_for(spec.family) if s.kind == TEST_LADDER
        )
        assert family_ladder == (spec,)
    assert {spec.family for spec in FORM_TEST_SPECS if spec.kind == TEST_LADDER} == {
        "debt_maturity",
        "commitments_contingencies",
    }


def test_stage_adapter_evaluates_the_declared_spec() -> None:
    spec = form_test_specs_for("debt_maturity")[0]
    result = evaluate_form_test_ladder(structure_table(DEBT_COLUMNS), spec)
    assert result.passed and result.axis == "columns"
    commitments = form_test_specs_for("commitments_contingencies")[0]
    result = evaluate_form_test_ladder(structure_table(PAYMENTS_DUE), commitments)
    assert result.passed and result.kind == "bucket"


def test_debt_column_ladder_passes_with_total() -> None:
    assert DEBT is not None
    result = evaluate_year_ladder(DEBT_COLUMNS, DEBT)
    assert result.passed and result.axis == "columns" and result.kind == "year"
    assert result.thereafter is True and result.total_reconciles is True
    assert [step.start for step in result.steps] == [2026, 2027, 2028, 2029, 2030, 0]


def test_debt_row_ladder_passes() -> None:
    assert DEBT is not None
    context = _context(
        (
            ("Fiscal year", "Amount"),
            ("2026", "100"),
            ("2027", "200"),
            ("2028", "300"),
            ("2029", "400"),
            ("Thereafter", "500"),
            ("Total", "1,500"),
        )
    )
    result = evaluate_year_ladder(context, DEBT)
    assert result.passed and result.axis == "rows" and result.total_reconciles is True


def test_payments_due_bucket_ladder_is_commitments_form_not_debt() -> None:
    assert DEBT is not None and COMMITMENTS is not None
    result = evaluate_year_ladder(PAYMENTS_DUE, COMMITMENTS)
    assert result.passed and result.kind == "bucket" and result.thereafter is True
    assert result.total_reconciles is True
    assert not evaluate_year_ladder(PAYMENTS_DUE, DEBT).passed


def test_short_year_ladder_admits_commitments_not_debt() -> None:
    assert DEBT is not None and COMMITMENTS is not None
    context = _context(
        (
            ("", "2026", "2027", "2028", "Thereafter"),
            ("Lease obligations", "10", "20", "30", "40"),
        )
    )
    assert evaluate_year_ladder(context, COMMITMENTS).passed
    assert not evaluate_year_ladder(context, DEBT).passed


def test_ladder_year_recognizers_are_range_ruled() -> None:
    """Delta pin: as-of, range, and thereafter years are the homed
    1900-9999 token; the deleted private copies accepted 0000-9999."""
    assert _asof_year(("Maturities as of December 31, 2024",), ()) == 2024
    assert _asof_year(("Maturities as of December 31, 1899",), ()) is None
    step = _step_for_label("2025 to 2027")
    assert step is not None and step.kind == "range" and step.start == 2025
    degraded = _step_for_label("1899 to 2027")
    assert degraded is not None and degraded.kind == "year"
    assert degraded.start == 2027
    open_step = _step_for_label("Thereafter")
    assert open_step is not None and open_step.kind == "open"


def test_year_cell_uses_the_homed_recognition() -> None:
    """Delta pin: _is_year_cell collapsed onto is_year_token; the
    home's recognition is the full-range 1900-9999 shape."""
    from edgar_sec.engine.tables.extraction.form_tests.year_ladder import _is_year_cell

    assert _is_year_cell("2024")
    assert _is_year_cell("2100")
    assert _is_year_cell("2150")
    assert not _is_year_cell("1899")


def test_anchored_ladder_starts_after_the_balance_sheet_date() -> None:
    assert DEBT is not None
    context = _context(
        (
            ("Maturities as of December 31, 2024",),
            ("", "2025", "2026", "2027", "2028", "2029", "Thereafter"),
            ("Long-term debt", "10", "20", "30", "40", "50", "60"),
        )
    )
    assert evaluate_year_ladder(context, DEBT).passed


def test_composition_by_instrument_fails() -> None:
    assert DEBT is not None and COMMITMENTS is not None
    context = _context(
        (
            ("", "Term loan", "Revolver", "Senior notes", "Total"),
            ("Debt", "100", "200", "300", "600"),
        )
    )
    assert not evaluate_year_ladder(context, DEBT).passed
    assert not evaluate_year_ladder(context, COMMITMENTS).passed


def test_two_date_and_historical_stacks_fail() -> None:
    assert DEBT is not None
    balance_sheet = _context(
        (
            ("", "December 31, 2024", "December 31, 2023"),
            ("Long-term debt", "900", "850"),
        )
    )
    historical = _context(
        (
            ("As of December 31, 2024",),
            ("", "2022", "2023", "2024"),
            ("Revenue", "10", "20", "30"),
        )
    )
    assert not evaluate_year_ladder(balance_sheet, DEBT).passed
    assert not evaluate_year_ladder(historical, DEBT).passed


def test_broken_ladders_fail() -> None:
    assert DEBT is not None and COMMITMENTS is not None
    skipped_year = _context(
        (
            ("", "2026", "2028", "2029", "2030", "Thereafter"),
            ("Long-term debt", "10", "20", "30", "40", "50"),
        )
    )
    blank_step = _context(
        (
            ("", "2026", "2027", "2028", "2029", "2030", "Thereafter"),
            ("Long-term debt", "10", "20", "30", "40", "", "50"),
        )
    )
    bad_total = _context(
        (
            ("", "2026", "2027", "2028", "2029", "2030", "Total"),
            ("Long-term debt", "10", "20", "30", "40", "50", "999"),
        )
    )
    scrambled_buckets = _context(
        (
            (
                "",
                "Total",
                "3 to 5 years",
                "Less than 1 year",
                "1 to 3 years",
                "More than 5 years",
            ),
            ("Purchase obligations", "1,000", "200", "400", "300", "100"),
        )
    )
    assert not evaluate_year_ladder(skipped_year, DEBT).passed
    assert not evaluate_year_ladder(blank_step, DEBT).passed
    assert not evaluate_year_ladder(bad_total, DEBT).passed
    assert not evaluate_year_ladder(scrambled_buckets, COMMITMENTS).passed


def test_ladder_without_total_passes_with_no_total_verdict() -> None:
    assert DEBT is not None
    context = _context(
        (
            ("", "2026", "2027", "2028", "2029", "2030"),
            ("Long-term debt", "10", "20", "30", "40", "50"),
        )
    )
    result = evaluate_year_ladder(context, DEBT)
    assert result.passed and result.total_reconciles is None
