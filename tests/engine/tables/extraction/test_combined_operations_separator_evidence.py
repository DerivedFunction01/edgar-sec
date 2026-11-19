"""Combined operations separator (TEST_COMBINED_OPERATIONS_SEPARATOR): legs, gate, pass."""

from __future__ import annotations

from dataclasses import replace

import edgar_sec.engine.tables.extraction.combined_operations_separator_evidence as _evidence
import edgar_sec.engine.tables.extraction.measure_set as _measure_set
from edgar_sec.engine.tables.ascii_html.model import (
    ResolvedGrid,
    TableGeometry,
    TableRenderResult,
)
from edgar_sec.engine.tables.extraction.combined_operations_separator_evidence import (
    apply_combined_operations_assignment,
    evaluate_combined_operations_separator,
    failing_combined_operations_separator_outcome,
    separator_facts,
)
from edgar_sec.engine.tables.extraction.combined_operations_separator_specs import (
    COMBINED_OPERATIONS_SEPARATOR_SPECS,
    CORE_GROUP_INDICES,
    MEASURE_SET_TEST_ID,
)
from edgar_sec.engine.tables.extraction.competition import GeometryText, compete
from edgar_sec.engine.tables.extraction.context import TableContext
from edgar_sec.engine.tables.extraction.form_test_specs import FORM_TEST_SPECS
from edgar_sec.engine.tables.extraction.form_tests import (
    FormTestOutcome,
    evaluate_form_tests,
)
from edgar_sec.engine.tables.extraction.geometry_scoring import (
    CompetitionResult,
    FamilyScore,
)
from edgar_sec.engine.tables.extraction.measure_set_specs import (
    MEASURE_SET_SPECS_BY_TEST_ID,
)
from edgar_sec.engine.tables.extraction.profiles import (
    PROV_COMBINED_OPERATIONS_SEPARATOR,
    TEST_COMBINED_OPERATIONS_SEPARATOR,
    TEST_MEASURE_SET,
    profile_for,
)
from edgar_sec.engine.tables.extraction.typed_rows import TypedTable, structure_table
from edgar_sec.foundation.text.dates import (
    STRICT_YEAR_TOKEN_PATTERN as _HOME_STRICT_YEAR,
)

SPEC = COMBINED_OPERATIONS_SEPARATOR_SPECS["combined_operations_ci"]
FAMILY = "combined_operations_ci"


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


def _eval(rows: tuple[tuple[str, ...], ...], spec=SPEC):
    return evaluate_combined_operations_separator(_table(rows), spec)


_FULL = (
    ("", "December 31, 2024", "December 31, 2023"),
    ("Revenues", "1,000", "900"),
    ("Cost of revenues", "600", "550"),
    ("Gross profit", "400", "350"),
    ("Operating expenses", "200", "180"),
    ("Operating income", "200", "170"),
    ("Other income", "10", "5"),
    ("Income before income taxes", "210", "175"),
    ("Net income", "150", "120"),
    ("Other comprehensive income:", "", ""),
    ("Foreign currency translation adjustments", "20", "10"),
    ("Comprehensive income", "170", "130"),
)


def test_kind_is_declared_as_form_test_data():
    entry = next(
        s
        for s in FORM_TEST_SPECS
        if s.family == FAMILY and s.kind == TEST_COMBINED_OPERATIONS_SEPARATOR
    )
    assert entry.test_id == "combined_operations_ci_separator"
    assert entry.points == 0.0
    assert entry.provenance == PROV_COMBINED_OPERATIONS_SEPARATOR
    assert SPEC.family == FAMILY
    assert TEST_COMBINED_OPERATIONS_SEPARATOR in profile_for(FAMILY).form_tests


def test_core_group_indices_name_the_typed_core():
    groups = MEASURE_SET_SPECS_BY_TEST_ID[MEASURE_SET_TEST_ID].groups
    assert CORE_GROUP_INDICES == (0, 1, 3)
    assert "gross profit" in groups[0]
    assert groups[1] == ("net income", "net loss", "net earnings")
    assert "other comprehensive income" in groups[2]
    assert "comprehensive income" in groups[3]


def test_recognizer_and_presence_homes():
    assert _evidence._YEAR_RE.pattern == _HOME_STRICT_YEAR
    assert _evidence.group_presence is _measure_set.group_presence
    assert _evidence.evaluate_measure_set is _measure_set.evaluate_measure_set


# ---------------- the claim-local legs ----------------


def test_full_form_is_clear_with_core_facts():
    verdict = _eval(_FULL)
    assert not verdict.fired
    assert verdict.fired_legs == ()
    assert verdict.core_satisfied
    assert verdict.form_rank == 2
    assert verdict.detail == "coci separator clear core=1 rank=2"


def test_leg_s1_rows():
    rows = (
        ("", "December 31, 2024", "December 31, 2023"),
        ("Cost of revenues", "600", "550"),
        ("Gross profit", "400", "350"),
        ("Operating income", "200", "170"),
        ("Net income", "150", "120"),
        ("Other comprehensive income", "20", "10"),
        ("Foreign currency translation adjustments", "5", "2"),
        ("Comprehensive income", "170", "130"),
        ("Total other", "1", "1"),
    )
    verdict = _eval(rows)
    assert verdict.fired_legs == ("S1_rows",)


def test_leg_s2_numshare():
    stubs = (
        "Cost of revenues",
        "Gross profit",
        "Operating expenses",
        "Operating income",
        "Other income",
        "Income before income taxes",
        "Net income",
        "Other comprehensive income",
        "Foreign currency translation adjustments",
        "Comprehensive income",
    )
    rows = (("", "December 31, 2024", "December 31, 2023"),) + tuple(
        (stub, "100" if index < 2 else "", "90" if index < 2 else "")
        for index, stub in enumerate(stubs)
    )
    verdict = _eval(rows)
    assert "S2_numshare" in verdict.fired_legs
    assert "S1_rows" not in verdict.fired_legs


def test_leg_s3_span_ships_at_five_year_columns():
    rows = (("", "2024", "2023", "2022", "2021"),) + tuple(
        (stub, "100", "90", "", "") for stub, *_ in _FULL[1:]
    )
    verdict = _eval(rows)
    assert "S3_span" not in verdict.fired_legs
    derived = _eval(rows, replace(SPEC, min_year_columns=4))
    assert "S3_span" in derived.fired_legs
    wider = (("", "2025", "2024", "2023", "2022", "2021"),) + tuple(
        (stub, "100", "90", "", "", "") for stub, *_ in _FULL[1:]
    )
    assert "S3_span" in _eval(wider).fired_legs


def test_leg_c1_core_absent():
    dropped = ("Comprehensive income", "Other comprehensive income:")
    rows = tuple(row for row in _FULL if row[0] not in dropped) + (
        ("Interest expense", "30", "25"),
        ("Total other items", "1", "1"),
    )
    verdict = _eval(rows)
    assert verdict.fired_legs == ("C1_core",)
    assert not verdict.core_satisfied


def test_joint_form_ranks_below_full_and_satisfies_core():
    stubs = (
        "Operating income",
        "Net income and comprehensive income",
        "Cost of revenues",
        "Gross profit",
        "Operating expenses",
        "Other income",
        "Income before income taxes",
        "Interest expense",
        "Equity in earnings",
        "Total other",
    )
    rows = (("", "December 31, 2024", "December 31, 2023"),) + tuple(
        (stub, "100", "90") for stub in stubs
    )
    verdict = _eval(rows)
    assert not verdict.fired
    assert verdict.core_satisfied
    assert verdict.form_rank == 1


def test_facts_round_trip_through_the_stamped_outcome():
    outcomes = evaluate_form_tests(_table(_FULL))
    assert separator_facts(outcomes) == (True, 2)
    assert failing_combined_operations_separator_outcome(outcomes) is None
    fired = evaluate_form_tests(_table(_FULL[:2]))
    assert failing_combined_operations_separator_outcome(fired) is not None


# ---------------- the compete() gate (binds after seat-at-floor) ----------------


def _seat_outcome(passed: bool) -> FormTestOutcome:
    return FormTestOutcome(
        FAMILY,
        "combined_operations_ci_measure_set",
        TEST_MEASURE_SET,
        passed,
        True,
        0,
        3.0,
        "4 of 4 measure groups present (needs 4)",
    )


def _separator_outcome(passed: bool, detail: str) -> FormTestOutcome:
    return FormTestOutcome(
        FAMILY,
        "combined_operations_ci_separator",
        TEST_COMBINED_OPERATIONS_SEPARATOR,
        passed,
        True,
        0,
        0.0,
        detail,
    )


def test_gate_refuses_a_seated_claim_the_separator_fired_on():
    geometry = GeometryText(
        form_tests=(
            _seat_outcome(True),
            _separator_outcome(False, "coci separator fired: C1_core core=0 rank=2"),
        )
    )
    result = compete(geometry, scores={})
    assert FAMILY not in result.claims
    evidence = result.scores[FAMILY].evidence
    assert any(item.channel == "gate" for item in evidence)


def test_gate_keeps_a_seated_claim_the_separator_clears():
    geometry = GeometryText(
        form_tests=(
            _seat_outcome(True),
            _separator_outcome(True, "coci separator clear core=1 rank=2"),
        )
    )
    result = compete(geometry, scores={})
    assert FAMILY in result.claims


# ---------------- the set-level pass ----------------


def _geometry(*outcomes: FormTestOutcome) -> GeometryText:
    return GeometryText(form_tests=outcomes)


def _result(claims, totals, contested=(), foreign_explained=None) -> CompetitionResult:
    return CompetitionResult(
        claims=tuple(claims),
        contested=tuple(contested),
        scores={
            family: FamilyScore(family, total, {}, ()) for family, total in totals.items()
        },
        foreign_explained=dict(foreign_explained or {}),
        groups=(),
    )


def _descent_outcome(passed: bool) -> FormTestOutcome:
    return FormTestOutcome(
        "income_statement",
        "revenue_to_net_income_descent",
        TEST_MEASURE_SET,
        passed,
        True,
        0,
        3.0,
        "descent",
    )


def test_j1_seats_the_core_primary_over_a_higher_score():
    geometry = _geometry(
        _separator_outcome(True, "coci separator clear core=1 rank=2"),
        _descent_outcome(False),
    )
    result = _result(
        (FAMILY, "income_statement"),
        {FAMILY: 5.0, "income_statement": 7.0},
        contested=("income_statement",),
        foreign_explained={"income_statement": 1.5},
    )
    (out,) = apply_combined_operations_assignment([geometry], [result])
    assert out.claims == (FAMILY,)
    assert out.contested == ()
    assert out.foreign_explained == {"income_statement": 1.5}
    evidence = out.scores["income_statement"].evidence
    assert any(item.channel == "gate" for item in evidence)


def test_j1_drops_this_family_when_the_sibling_is_core():
    geometry = _geometry(
        _separator_outcome(True, "coci separator clear core=0 rank=0"),
        _descent_outcome(True),
    )
    result = _result(
        (FAMILY, "income_statement"), {FAMILY: 9.0, "income_statement": 4.0}
    )
    (out,) = apply_combined_operations_assignment([geometry], [result])
    assert out.claims == ("income_statement",)


def test_a1_corekeep_stands_core_and_best_non_core():
    core = _geometry(_separator_outcome(True, "coci separator clear core=1 rank=2"))
    best = _geometry(_separator_outcome(True, "coci separator clear core=0 rank=0"))
    worst = _geometry(_separator_outcome(True, "coci separator clear core=0 rank=0"))
    results = [
        _result((FAMILY,), {FAMILY: 5.0}),
        _result((FAMILY,), {FAMILY: 9.0}),
        _result((FAMILY,), {FAMILY: 3.0}),
    ]
    out = apply_combined_operations_assignment([core, best, worst], results)
    assert out[0].claims == (FAMILY,)
    assert out[1].claims == (FAMILY,)
    assert out[2].claims == ()


def test_a1_corekeep_keeps_the_best_non_core_candidate():
    low = _geometry(_separator_outcome(True, "coci separator clear core=0 rank=0"))
    high = _geometry(_separator_outcome(True, "coci separator clear core=0 rank=0"))
    results = [_result((FAMILY,), {FAMILY: 3.0}), _result((FAMILY,), {FAMILY: 8.0})]
    out = apply_combined_operations_assignment([low, high], results)
    assert out[0].claims == ()
    assert out[1].claims == (FAMILY,)


def test_pass_is_inert_on_a_single_claim():
    geometry = _geometry(_separator_outcome(True, "coci separator clear core=1 rank=2"))
    result = _result((FAMILY,), {FAMILY: 5.0})
    (out,) = apply_combined_operations_assignment([geometry], [result])
    assert out.claims == (FAMILY,)
