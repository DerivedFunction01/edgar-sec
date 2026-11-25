"""Goodwill separator (TEST_GOODWILL_SEPARATOR): conjunction, gate."""

from __future__ import annotations

import edgar_sec.engine.tables.extraction.note_separators.goodwill_separator_evidence as _gse
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
    PROV_GOODWILL_SEPARATOR,
    TEST_GOODWILL_SEPARATOR,
)
from edgar_sec.engine.tables.extraction.core.subjects.profiles import (
    profile_for,
)
from edgar_sec.engine.tables.extraction.note_separators.goodwill_separator_evidence import (
    evaluate_form_test_goodwill_separator,
    evaluate_goodwill_separator,
)
from edgar_sec.engine.tables.extraction.note_separators.goodwill_separator_specs import (
    GOODWILL_SEPARATOR_SPECS,
)
from edgar_sec.engine.tables.extraction.evidence.rollforward_grid_evidence import (
    RollforwardGridText,
)
from edgar_sec.engine.tables.extraction.core.typed_rows import structure_table

SPEC = GOODWILL_SEPARATOR_SPECS["goodwill_rollforward"]
FAMILY = "goodwill_rollforward"


def _eval(table_text: str):
    return evaluate_goodwill_separator(RollforwardGridText(table_text), SPEC)


def test_kind_is_declared_as_form_test_data():
    entry = next(
        s
        for s in FORM_TEST_SPECS
        if s.family == FAMILY and s.kind == TEST_GOODWILL_SEPARATOR
    )
    assert entry.test_id == "goodwill_separator"
    assert entry.points == 0.0
    assert entry.provenance == PROV_GOODWILL_SEPARATOR
    assert SPEC.family == FAMILY
    assert TEST_GOODWILL_SEPARATOR in profile_for(FAMILY).form_tests


def test_spec_carries_the_priced_conjunction():
    legs = [(leg.leg_id, leg.kind, leg.scope) for leg in SPEC.legs]
    assert legs == [
        ("alloc_columns", "allocation_columns", "claim-local"),
        ("goodwill_acquired_line", "goodwill_acquired_line", "claim-local"),
        ("no_bookend_walk", "no_bookend_walk", "claim-local"),
    ]


def test_recognizer_homes():
    assert _gse.fired_separator_outcome is _CORE_FORM_OUTCOME


# ---------------- the priced conjunction ----------------

_ALLOCATION = (
    " | Preliminary allocation at December 31, 2023 | Measurement period"
    " adjustments | Final allocation\n"
    "Trade receivables | $ | 1,883 | $ | — | $ | 1,883\n"
    "Inventory and other current assets | 500 | 10 | 510\n"
    "Property, plant, and equipment | 700 | 0 | 700\n"
    "Goodwill | 2,000 | 100 | 2,100\n"
    "Liabilities assumed | (300) | 0 | (300)\n"
    "Total | 4,803 | 110 | 4,913"
)


def test_conjunction_fires_on_the_allocation_form():
    verdict = _eval(_ALLOCATION)
    assert verdict.fired
    assert verdict.legs == (
        "alloc_columns",
        "goodwill_acquired_line",
        "no_bookend_walk",
    )


def test_packet_and_rows_surfaces_agree():
    rows = (
        ("", "Preliminary allocation", "Final allocation"),
        ("Goodwill", "2,000", "2,100"),
        ("Liabilities assumed", "(300)", "(300)"),
    )
    via_rows = evaluate_goodwill_separator(RollforwardGridText.from_rows(rows), SPEC)
    via_packet = evaluate_goodwill_separator(
        RollforwardGridText.from_packet(
            {
                "table_text": " | Preliminary allocation | Final allocation\n"
                "Goodwill | 2,000 | 2,100\n"
                "Liabilities assumed | (300) | (300)"
            }
        ),
        SPEC,
    )
    assert via_rows == via_packet
    assert via_rows.fired


_WALK = (
    "Balance, beginning of period | 1,000\n"
    "Acquisitions | 200\n"
    "Impairments | (50)\n"
    "Balance, end of period | 1,150"
)


def test_clear_on_a_bookend_walk():
    verdict = _eval(_WALK)
    assert not verdict.fired


def test_bookend_walk_blocks_even_with_allocation_columns():
    text = (
        _ALLOCATION
        + "\nBalance, beginning of period | 900\nBalance, end of period | 950"
    )
    verdict = _eval(text)
    assert not verdict.fired


def test_clear_without_the_goodwill_line():
    verdict = _eval(_ALLOCATION.replace("Goodwill |", "Trademarks |"))
    assert not verdict.fired


def test_clear_without_the_column_pair():
    text = (
        "Assets acquired | Amount\n"
        "Goodwill | 2,100\n"
        "Liabilities assumed | (300)\n"
        "Total | 4,913"
    )
    verdict = _eval(text)
    assert not verdict.fired


def test_clear_with_only_a_preliminary_column():
    text = _ALLOCATION.replace(" | Final allocation", " | As reported")
    verdict = _eval(text)
    assert not verdict.fired


def test_empty_grid_is_unevaluable():
    verdict = _eval("")
    assert not verdict.fired
    assert not verdict.evaluable


# ---------------- stage adapter + dispatch ----------------


def _table(rows):
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
    context = TableContext(geometry=geometry, caption_stack=(), prose_before="")
    return structure_table(context)


_ALLOC_ROWS = (
    (
        "",
        "Preliminary allocation",
        "Measurement period adjustments",
        "Final allocation",
    ),
    ("Trade receivables", "1,883", "—", "1,883"),
    ("Goodwill", "2,000", "100", "2,100"),
    ("Liabilities assumed", "(300)", "0", "(300)"),
)


def test_stage_adapter_over_full_grid():
    table = _table(_ALLOC_ROWS)
    spec = next(s for s in FORM_TEST_SPECS if s.test_id == "goodwill_separator")
    verdict = evaluate_form_test_goodwill_separator(table, spec)
    assert verdict.fired
    assert "alloc_columns" in verdict.legs


def test_stage_dispatch_stamps_separator_outcome():
    table = _table(_ALLOC_ROWS)
    outcomes = {o.test_id: o for o in evaluate_form_tests(table)}
    outcome = outcomes["goodwill_separator"]
    assert outcome.kind == TEST_GOODWILL_SEPARATOR
    assert not outcome.passed and outcome.evaluable
    assert outcome.points == 0.0


# ---------------- competition gate ----------------

_SCORE = {FAMILY: FamilyScore(FAMILY, 11.0, {"signature": 11.0}, ())}


def _outcome(passed: bool, evaluable: bool = True) -> FormTestOutcome:
    return FormTestOutcome(
        FAMILY,
        "goodwill_separator",
        TEST_GOODWILL_SEPARATOR,
        passed,
        evaluable,
        0,
        0.0,
        "separator fired: alloc_columns",
    )


def test_gate_removes_claim_on_fired_outcome():
    geometry = GeometryText(form_tests=(_outcome(False),))
    result = compete(geometry, scores=dict(_SCORE))
    assert FAMILY not in result.claims
    evidence = result.scores[FAMILY].evidence
    assert any(
        item.channel == "gate" and "separator fired" in item.detail for item in evidence
    )


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
