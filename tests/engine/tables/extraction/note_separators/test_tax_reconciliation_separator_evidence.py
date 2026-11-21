"""Tax reconciliation separator (TEST_TAX_RECONCILIATION_SEPARATOR): legs, gate."""

from __future__ import annotations

import edgar_sec.engine.tables.extraction.note_separators.tax_reconciliation_separator_evidence as _tse
from edgar_sec.engine.tables.ascii_html.model import (
    ResolvedGrid,
    TableGeometry,
    TableRenderResult,
)
from edgar_sec.engine.tables.extraction.cascade.competition import compete
from edgar_sec.engine.tables.extraction.cascade.geometry_text import GeometryText
from edgar_sec.engine.tables.extraction.core.context import TableContext
from edgar_sec.engine.tables.extraction.evidence.core_form_evidence import (
    failing_core_form_outcome as _CORE_FORM_OUTCOME,
)
from edgar_sec.engine.tables.extraction.form_specs.form_test_specs import (
    FORM_TEST_SPECS,
)
from edgar_sec.engine.tables.extraction.form_specs.form_test_types import (
    FormTestOutcome,
)
from edgar_sec.engine.tables.extraction.form_tests.form_tests import evaluate_form_tests
from edgar_sec.engine.tables.extraction.cascade.geometry_scoring import FamilyScore
from edgar_sec.engine.tables.extraction.core.profiles import (
    PROV_TAX_RECONCILIATION_SEPARATOR,
    TEST_TAX_EVIDENCE,
    TEST_TAX_RECONCILIATION_SEPARATOR,
    profile_for,
)
from edgar_sec.engine.tables.extraction.note_separators.tax_reconciliation_separator_evidence import (
    TaxReconciliationSeparatorText,
    evaluate_form_test_tax_reconciliation_separator,
    evaluate_tax_reconciliation_separator,
    movement_nonzero,
    rate_core_present,
)
from edgar_sec.engine.tables.extraction.note_separators.tax_reconciliation_separator_specs import (
    TAX_RECONCILIATION_SEPARATOR_SPECS,
)
from edgar_sec.engine.tables.extraction.core.typed_rows import structure_table
from edgar_sec.engine.forms.common.numbers import SCHEMA_PERCENT_RE as _HOME_PCT_RE
from edgar_sec.foundation.text.patterns import RE_WHITESPACE as _HOME_WS_RE

SPEC = TAX_RECONCILIATION_SEPARATOR_SPECS["tax_reconciliation"]
FAMILY = "tax_reconciliation"

_FIRING = (
    "Income from continuing operations | $ | 25,157\n"
    "Gain on sales of discontinued operations | | 1,200\n"
    "Income tax expense | | 3,400"
)


def _eval(table_text: str):
    return evaluate_tax_reconciliation_separator(
        TaxReconciliationSeparatorText(table_text), SPEC
    )


def test_kind_is_declared_as_form_test_data():
    entry = next(
        s
        for s in FORM_TEST_SPECS
        if s.family == FAMILY and s.kind == TEST_TAX_RECONCILIATION_SEPARATOR
    )
    assert entry.test_id == "tax_reconciliation_separator"
    assert entry.points == 0.0
    assert entry.provenance == PROV_TAX_RECONCILIATION_SEPARATOR
    assert SPEC.family == FAMILY
    assert TEST_TAX_RECONCILIATION_SEPARATOR in profile_for(FAMILY).form_tests


def test_spec_carries_the_priced_conjunction():
    assert SPEC.max_rows == 8


def test_packet_and_rows_surfaces_agree():
    rows = (
        ("Income from continuing operations", "$", "25,157"),
        ("Gain on sales of discontinued operations", "", "1,200"),
        ("Income tax expense", "", "3,400"),
    )
    via_rows = evaluate_tax_reconciliation_separator(
        TaxReconciliationSeparatorText.from_rows(rows), SPEC
    )
    via_packet = evaluate_tax_reconciliation_separator(
        TaxReconciliationSeparatorText.from_packet({"table_text": _FIRING}),
        SPEC,
    )
    assert via_rows == via_packet
    assert via_rows.fired


def test_recognizer_homes():
    assert _tse.RE_WHITESPACE is _HOME_WS_RE
    assert _tse.SCHEMA_PERCENT_RE is _HOME_PCT_RE
    assert _tse.fired_separator_outcome is _CORE_FORM_OUTCOME


# ---------------- the priced conjunction ----------------


def test_conjunction_fires_on_the_priced_shape():
    verdict = _eval(_FIRING)
    assert verdict.fired
    assert verdict.legs == ("det_core_absent", "move_nonzero_le_0", "rows_le_8")


def test_core_present_clears():
    text = (
        "Statutory federal income tax rate | 35%\n"
        "State taxes, net of federal benefit | 2%\n"
        "Effective income tax rate | 37%"
    )
    verdict = _eval(text)
    assert not verdict.fired
    assert rate_core_present(TaxReconciliationSeparatorText(text))


def test_anchor_without_rate_rows_is_not_core():
    text = "Statutory rate reconciliation | 100\nOther items | 200"
    assert not rate_core_present(TaxReconciliationSeparatorText(text))
    assert _eval(text).fired


def test_movement_nonzero_clears():
    text = _FIRING + "\nProvision for income taxes | 500"
    verdict = _eval(text)
    assert not verdict.fired
    assert movement_nonzero(TaxReconciliationSeparatorText(text)) == 1


def test_movement_zero_values_do_not_count():
    text = _FIRING + "\nProvision for income taxes | —"
    verdict = _eval(text)
    assert verdict.fired
    assert movement_nonzero(TaxReconciliationSeparatorText(text)) == 0


def test_rows_above_eight_clears():
    extra = "\n".join(f"Other item {i} | {i}" for i in range(6))
    verdict = _eval(_FIRING + "\n" + extra)
    assert not verdict.fired


def test_rows_at_eight_fires():
    extra = "\n".join(f"Other item {i} | {i}" for i in range(5))
    verdict = _eval(_FIRING + "\n" + extra)
    assert verdict.fired


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


def test_stage_adapter_over_full_grid():
    table = _table(
        (
            ("Income from continuing operations", "$", "25,157"),
            ("Gain on sales of discontinued operations", "", "1,200"),
            ("Income tax expense", "", "3,400"),
        )
    )
    spec = next(
        s for s in FORM_TEST_SPECS if s.test_id == "tax_reconciliation_separator"
    )
    verdict = evaluate_form_test_tax_reconciliation_separator(table, spec)
    assert verdict.fired
    assert "det_core_absent" in verdict.legs


def test_stage_dispatch_stamps_separator_outcome():
    table = _table(
        (
            ("Income from continuing operations", "$", "25,157"),
            ("Gain on sales of discontinued operations", "", "1,200"),
            ("Income tax expense", "", "3,400"),
        )
    )
    outcomes = {o.test_id: o for o in evaluate_form_tests(table)}
    outcome = outcomes["tax_reconciliation_separator"]
    assert outcome.kind == TEST_TAX_RECONCILIATION_SEPARATOR
    assert not outcome.passed and outcome.evaluable
    assert outcome.points == 0.0


# ---------------- competition gate ----------------

_SCORE = {FAMILY: FamilyScore(FAMILY, 11.0, {"signature": 11.0}, ())}


def _outcome(passed: bool, evaluable: bool = True) -> FormTestOutcome:
    return FormTestOutcome(
        FAMILY,
        "tax_reconciliation_separator",
        TEST_TAX_RECONCILIATION_SEPARATOR,
        passed,
        evaluable,
        0,
        0.0,
        "separator fired: det_core_absent, move_nonzero_le_0, rows_le_8",
    )


# The landed seat displaces a scored claim and re-seats it
# only on a passed seat outcome; keeps geometries carry one.
def _seat_outcome() -> FormTestOutcome:
    return FormTestOutcome(
        FAMILY,
        "tax_reconciliation_statutory_anchor_seat",
        TEST_TAX_EVIDENCE,
        True,
        True,
        0,
        0.0,
        "anchor 'statutory' in stub; context 'tax' in lead",
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
    geometry = GeometryText(form_tests=(_outcome(True), _seat_outcome()))
    result = compete(geometry, scores=dict(_SCORE))
    assert FAMILY in result.claims


def test_gate_keeps_claim_when_outcome_absent():
    geometry = GeometryText(form_tests=(_seat_outcome(),))
    result = compete(geometry, scores=dict(_SCORE))
    assert FAMILY in result.claims


def test_gate_keeps_claim_when_outcome_unevaluable():
    geometry = GeometryText(
        form_tests=(_outcome(False, evaluable=False), _seat_outcome())
    )
    result = compete(geometry, scores=dict(_SCORE))
    assert FAMILY in result.claims
