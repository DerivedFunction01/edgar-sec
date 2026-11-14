"""Labor capture: linkage generates, fields bind inside the span."""

from __future__ import annotations

from edgar_sec.engine.tables.extraction.labor_capture import capture_labor

_FULL = (
    "Substantially all of the plant's works employees are covered by a "
    "collective bargaining agreement with UAW Local 3462 representing "
    "approximately 330 employees. The agreement was ratified in "
    "March 2013 and expires March 31, 2016."
)


def test_full_shape_binds_group_union_and_terms() -> None:
    rows = capture_labor(_FULL)
    carriers = [row for row in rows if not row.negated]
    assert carriers
    row = carriers[0]
    assert row.union == "UAW Local 3462"
    assert row.employee_count == 330
    assert any("2016" in term for term in row.contract_terms)


def test_expiration_date_alone_never_generates() -> None:
    prose = "The warrants expire on their expiration date, June 1, 2027."
    assert capture_labor(prose) == ()


def test_negation_is_a_zero_fact_not_a_carrier() -> None:
    prose = (
        "None of our employees are represented by any collective "
        "bargaining unit or union."
    )
    rows = capture_labor(prose)
    assert len(rows) == 1
    assert rows[0].negated
    assert rows[0].union is None


def test_group_and_contract_without_union_name_still_binds() -> None:
    prose = (
        "Warehouse associates are covered by a collective bargaining "
        "agreement that expires December 31, 2026."
    )
    rows = capture_labor(prose)
    assert len(rows) == 1
    assert rows[0].union is None
    assert any("2026" in term for term in rows[0].contract_terms)


def test_unrelated_prose_yields_nothing() -> None:
    assert capture_labor("Revenue rose in the quarter. Margins held.") == ()
