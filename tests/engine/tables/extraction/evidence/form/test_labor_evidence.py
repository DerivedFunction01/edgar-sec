"""Labor-form seat: registry data, signature arms, claim act."""

from __future__ import annotations

from edgar_sec.engine.tables.ascii_html.model.model import (
    ResolvedGrid,
    TableGeometry,
    TableRenderResult,
)
from edgar_sec.engine.tables.extraction.cascade.competition import CLAIM_FLOOR, compete
from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_text import (
    geometry_text_from_table,
)
from edgar_sec.engine.tables.extraction.core.text.context import TableContext
from edgar_sec.engine.tables.extraction.form_specs.form_test_specs import (
    FORM_TEST_SPECS,
)
from edgar_sec.engine.tables.extraction.form_tests.form_tests import evaluate_form_tests
from edgar_sec.engine.tables.extraction.evidence.form.labor_evidence import (
    LaborText,
    apply_labor_seat,
    evaluate_form_test_labor,
    evaluate_labor_evidence,
)
from edgar_sec.engine.tables.extraction.specs.families.labor_specs import (
    LABOR_EVIDENCE_SPECS,
    LABOR_EVIDENCE_SPECS_BY_TEST_ID,
)
from edgar_sec.engine.tables.extraction.core.subjects.profiles import (
    PROV_S6B_PRICING,
    TEST_LABOR_FORM,
    profile_for,
)
from edgar_sec.engine.tables.extraction.core.registry import FAMILY_PRIORITY
from edgar_sec.engine.tables.extraction.core.typed_rows import structure_table

SPEC = LABOR_EVIDENCE_SPECS["labor_contracts"]

UAL_ROWS = (
    ("Employee Group", "Number of Employees", "Union", "Agreement Open"),
    ("Flight Attendants", "25,803", "Association of Flight Attendants", "2021"),
    ("Pilots", "12,400", "Air Line Pilots Association", "2023"),
)
NYT_ROWS = (
    ("Category", "Expiration Date"),
    ("Newspaper Guild", "2027"),
    ("Machinists", "2026"),
)


def _table(rows: tuple[tuple[str, ...], ...]):
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


def _verdict(rows: tuple[tuple[str, ...], ...]):
    return evaluate_labor_evidence(LaborText.from_table(_table(rows)), SPEC)


def test_seat_is_declared_as_form_test_data():
    entry = next(s for s in FORM_TEST_SPECS if s.family == "labor_contracts")
    assert entry.kind == TEST_LABOR_FORM
    assert entry.points == 0.0
    assert entry.provenance == PROV_S6B_PRICING
    assert LABOR_EVIDENCE_SPECS_BY_TEST_ID[entry.test_id] is SPEC
    assert TEST_LABOR_FORM in profile_for("labor_contracts").form_tests
    assert "labor_contracts" in FAMILY_PRIORITY


def test_priced_cells_are_the_covered_core():
    assert (SPEC.seated, SPEC.positives) == (36, 36)
    assert (SPEC.neg_t1_touched, SPEC.neg_t1_tables) == (0, 272)
    assert (SPEC.neg_t2_touched, SPEC.neg_t2_tables) == (0, 55)


def test_main_arm_seats_representative_plus_coverage():
    verdict = _verdict(UAL_ROWS)
    assert verdict.admitted and verdict.arm == "A3"


def test_arm3_seats_date_plus_stub_name_without_rep_header():
    verdict = _verdict(NYT_ROWS)
    assert verdict.admitted and verdict.arm == "ARM3"


def test_representative_header_without_coverage_refuses():
    rows = (
        ("Bargaining Unit", "Representative"),
        ("Unit A", "Some Union"),
        ("Unit B", "Other Union"),
    )
    assert not _verdict(rows).admitted


def test_coverage_header_without_representative_refuses():
    rows = (
        ("Employee Group", "Number of Employees", "Status"),
        ("Group A", "100", "Active"),
        ("Group B", "200", "Active"),
    )
    assert not _verdict(rows).admitted


def test_arm3_blocked_when_representative_header_present():
    rows = (
        ("Union", "Expiration Date"),
        ("Teamsters", "2027"),
        ("Machinists", "2026"),
    )
    assert not _verdict(rows).admitted


def test_demographics_shape_refuses_on_core():
    rows = (
        ("Workforce", "Total", "Women", "Minorities"),
        ("United States", "1,000", "40%", "30%"),
        ("Outside United States", "500", "35%", "45%"),
    )
    assert not _verdict(rows).admitted


def test_supporting_features_alone_never_seat():
    rows = (
        ("Group", "Description"),
        ("All", "Teamsters under a collective bargaining agreement"),
        ("None", "No representation"),
    )
    assert not _verdict(rows).admitted


def test_fragment_guard_refuses_tiny_signature_table():
    rows = (("Union", "Number of Employees", "Teamsters"),)
    verdict = _verdict(rows)
    assert not verdict.admitted and verdict.arm == "A3"


def test_fragment_guard_refuses_note_lead_table():
    rows = (
        ("(1)", "Union", "Number of Employees"),
        ("Teamsters", "50", "see note"),
        ("Machinists", "60", "see note"),
    )
    verdict = _verdict(rows)
    assert not verdict.admitted and verdict.arm == "A3"


def test_stage_outcome_passes_on_signature_table():
    spec = next(s for s in FORM_TEST_SPECS if s.family == "labor_contracts")
    result = evaluate_form_test_labor(_table(UAL_ROWS), spec)
    assert result.admitted
    outcomes = evaluate_form_tests(_table(UAL_ROWS))
    outcome = next(o for o in outcomes if o.test_id == "labor_contracts_form")
    assert outcome.passed and outcome.points == 0.0


def test_competition_seats_at_claim_floor():
    geometry = geometry_text_from_table(_table(UAL_ROWS))
    result = compete(geometry)
    assert "labor_contracts" in result.claims
    assert result.scores["labor_contracts"].total == CLAIM_FLOOR
    group = next(g for g in result.groups if g.family == "labor_contracts")
    assert group.state == "reach"


def test_unstamped_geometry_never_seats():
    geometry = geometry_text_from_table(_table(UAL_ROWS), evaluate_stage=False)
    assert "labor_contracts" not in compete(geometry).claims


def test_seat_act_guards():
    geometry = geometry_text_from_table(_table(UAL_ROWS))
    claims: list[str] = []
    reach: list[str] = []
    scores = apply_labor_seat(geometry, {}, claims, reach, {"labor_contracts"}, 5.0)
    assert scores == {} and claims == [] and reach == []
    scores = apply_labor_seat(geometry, {}, claims, reach, frozenset(), 5.0)
    assert scores["labor_contracts"].total == 5.0
    assert claims == ["labor_contracts"] and reach == ["labor_contracts"]
    again = apply_labor_seat(geometry, scores, claims, reach, frozenset(), 5.0)
    assert again is scores and claims == ["labor_contracts"]
