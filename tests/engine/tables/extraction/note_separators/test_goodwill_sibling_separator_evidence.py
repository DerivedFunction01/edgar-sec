"""Goodwill sibling-mass separator
(TEST_GOODWILL_SIBLING_SEPARATOR): conjunction, gate."""

from __future__ import annotations

import edgar_sec.engine.tables.extraction.note_separators.goodwill_sibling_separator_evidence as _gse
from edgar_sec.engine.tables.ascii_html.model.model import (
    ResolvedGrid,
    TableGeometry,
    TableRenderResult,
)
from edgar_sec.engine.tables.extraction.cascade.competition import compete
from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_text import (
    GeometryText,
)
from edgar_sec.engine.tables.extraction.core.text.context import TableContext
from edgar_sec.engine.tables.extraction.evidence.form.core_form_evidence import (
    failing_core_form_outcome as _CORE_FORM_OUTCOME,
)
from edgar_sec.engine.tables.extraction.form_specs.form_test_specs import (
    FORM_TEST_SPECS,
)
from edgar_sec.engine.tables.extraction.form_specs.form_test_types import (
    FormTestOutcome,
)
from edgar_sec.engine.tables.extraction.form_tests.form_tests import evaluate_form_tests
from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_scoring import (
    FamilyScore,
)
from edgar_sec.engine.tables.extraction.core.subjects.profile_constants import (
    PROV_GOODWILL_SIBLING_SEPARATOR,
    TEST_GOODWILL_SIBLING_SEPARATOR,
)
from edgar_sec.engine.tables.extraction.core.subjects.profiles import (
    profile_for,
)
from edgar_sec.engine.tables.extraction.note_separators.goodwill_sibling_separator_evidence import (
    evaluate_form_test_goodwill_sibling_separator,
    evaluate_goodwill_sibling_separator,
)
from edgar_sec.engine.tables.extraction.note_separators.goodwill_sibling_separator_specs import (
    GOODWILL_SIBLING_SEPARATOR_SPECS,
)
from edgar_sec.engine.tables.extraction.evidence.rollforward_grid_evidence import (
    RollforwardGridText,
)
from edgar_sec.engine.tables.extraction.core.typed_rows import structure_table

SPEC = GOODWILL_SIBLING_SEPARATOR_SPECS["goodwill_rollforward"]
FAMILY = "goodwill_rollforward"


def _eval(table_text: str, caption: str = ""):
    return evaluate_goodwill_sibling_separator(
        RollforwardGridText(table_text, caption), SPEC
    )


def test_kind_is_declared_as_form_test_data():
    entry = next(
        s
        for s in FORM_TEST_SPECS
        if s.family == FAMILY and s.kind == TEST_GOODWILL_SIBLING_SEPARATOR
    )
    assert entry.test_id == "goodwill_sibling_separator"
    assert entry.points == 0.0
    assert entry.provenance == PROV_GOODWILL_SIBLING_SEPARATOR
    assert SPEC.family == FAMILY
    assert TEST_GOODWILL_SIBLING_SEPARATOR in profile_for(FAMILY).form_tests


def test_spec_carries_the_priced_conjunction():
    legs = [(leg.leg_id, leg.kind, leg.scope) for leg in SPEC.legs]
    assert legs == [
        ("sibling_mass", "sibling_mass", "claim-local"),
        ("goodwill_not_stub_subject", "goodwill_not_stub_subject", "claim-local"),
    ]
    assert SPEC.legs[0].limit == 2.0


def test_recognizer_homes():
    assert _gse.fired_separator_outcome is _CORE_FORM_OUTCOME


# ---------------- the priced conjunction: kills ----------------

_COMPOSITION = (
    "December 31, 2024 | December 31, 2023\n"
    "Mastheads | 206,387 | 203,587\n"
    "Trademarks | 45,000 | 45,000\n"
    "Customer relationships | 12,300 | 13,100\n"
    "Total | 263,687 | 261,687"
)


def test_fires_on_sibling_class_composition():
    verdict = _eval(_COMPOSITION)
    assert verdict.fired
    assert verdict.legs == ("sibling_mass", "goodwill_not_stub_subject")


def test_fires_on_two_sibling_rows_only():
    text = (
        "Patents | 800\n"
        "Licenses | 300\n"
        "Total | 1,100"
    )
    assert _eval(text).fired


def test_fires_with_goodwill_only_in_a_later_cell():
    text = (
        "Mastheads | Goodwill impairment review | 206,387\n"
        "Trademarks |  | 45,000\n"
        "Total |  | 251,387"
    )
    assert _eval(text).fired


# ---------------- the priced conjunction: spares ----------------


def test_clear_on_combined_walk_with_goodwill_stub():
    text = (
        "Goodwill | 1,014,257 | 1,012,011\n"
        "Mastheads | 206,387 | 203,587\n"
        "Trademarks | 45,000 | 45,000\n"
        "Total | 1,265,644 | 1,260,598"
    )
    assert not _eval(text).fired


def test_clear_on_pure_goodwill_walk():
    text = (
        "Balance at December 31, 2023 | 3,000\n"
        "Business acquisition | 25\n"
        "Balance at December 31, 2024 | 3,025"
    )
    assert not _eval(text).fired


def test_clear_below_sibling_mass():
    text = (
        "Trademarks | 45,000\n"
        "Other assets | 12,000\n"
        "Total | 57,000"
    )
    assert not _eval(text).fired


def test_empty_grid_is_unevaluable():
    verdict = _eval("")
    assert not verdict.fired
    assert not verdict.evaluable


# ---------------- stage adapter + dispatch ----------------


def _table(rows, caption_stack=()):
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
    context = TableContext(
        geometry=geometry, caption_stack=caption_stack, prose_before=""
    )
    return structure_table(context)


_COMPOSITION_ROWS = (
    ("December 31, 2024", "December 31, 2023"),
    ("Mastheads", "206,387", "203,587"),
    ("Trademarks", "45,000", "45,000"),
    ("Customer relationships", "12,300", "13,100"),
    ("Total", "263,687", "261,687"),
)


def test_stage_adapter_over_full_grid():
    table = _table(_COMPOSITION_ROWS)
    spec = next(s for s in FORM_TEST_SPECS if s.test_id == "goodwill_sibling_separator")
    verdict = evaluate_form_test_goodwill_sibling_separator(table, spec)
    assert verdict.fired
    assert "sibling_mass" in verdict.legs


def test_stage_dispatch_stamps_separator_outcome():
    table = _table(_COMPOSITION_ROWS)
    outcomes = {o.test_id: o for o in evaluate_form_tests(table)}
    outcome = outcomes["goodwill_sibling_separator"]
    assert outcome.kind == TEST_GOODWILL_SIBLING_SEPARATOR
    assert not outcome.passed and outcome.evaluable
    assert outcome.points == 0.0


# ---------------- competition gate ----------------

_SCORE = {FAMILY: FamilyScore(FAMILY, 11.0, {"signature": 11.0}, ())}


def _outcome(passed: bool, evaluable: bool = True) -> FormTestOutcome:
    return FormTestOutcome(
        FAMILY,
        "goodwill_sibling_separator",
        TEST_GOODWILL_SIBLING_SEPARATOR,
        passed,
        evaluable,
        0,
        0.0,
        "sibling separator fired: sibling_mass",
    )


def test_gate_removes_claim_on_fired_outcome():
    geometry = GeometryText(form_tests=(_outcome(False),))
    result = compete(geometry, scores=dict(_SCORE))
    assert FAMILY not in result.claims
    evidence = result.scores[FAMILY].evidence
    assert any(
        item.channel == "gate" and "sibling separator fired" in item.detail
        for item in evidence
    )


def test_gate_binds_after_the_measure_set_seat():
    measure_set = FormTestOutcome(
        FAMILY,
        "goodwill_rollforward_measure_set",
        "measure_set",
        True,
        True,
        0,
        3.0,
        "measure set passed",
    )
    geometry = GeometryText(form_tests=(measure_set, _outcome(False)))
    result = compete(geometry, scores=dict(_SCORE))
    assert FAMILY not in result.claims


def test_gate_keeps_claim_on_clear_outcome():
    geometry = GeometryText(form_tests=(_outcome(True),))
    result = compete(geometry, scores=dict(_SCORE))
    assert FAMILY in result.claims


def test_gate_keeps_claim_when_outcome_absent():
    result = compete(GeometryText(), scores=dict(_SCORE))
    assert FAMILY in result.claims


def test_gate_keeps_claim_when_outcome_unevaluable():
    geometry = GeometryText(form_tests=(_outcome(False, evaluable=False),))
    result = compete(geometry, scores=dict(_SCORE))
    assert FAMILY in result.claims
