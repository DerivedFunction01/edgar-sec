"""Deferred tax separator (TEST_DEFERRED_TAX_SEPARATOR): legs, gate."""

from __future__ import annotations

import edgar_sec.engine.tables.extraction.note_separators.deferred_tax_separator_evidence as _dse
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
from edgar_sec.engine.tables.extraction.note_separators.deferred_tax_separator_evidence import (
    DeferredTaxSeparatorText,
    deferred_core_present,
    evaluate_deferred_tax_separator,
    evaluate_form_test_deferred_tax_separator,
)
from edgar_sec.engine.tables.extraction.note_separators.deferred_tax_separator_specs import (
    DEFERRED_TAX_SEPARATOR_SPECS,
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
    PROV_DEFERRED_TAX_SEPARATOR,
    TEST_DEFERRED_TAX_SEPARATOR,
    profile_for,
)
from edgar_sec.engine.tables.extraction.core.typed_rows import structure_table

SPEC = DEFERRED_TAX_SEPARATOR_SPECS["deferred_tax"]
FAMILY = "deferred_tax"

_FIRING_SHARES = (
    "Shares reserved for issuance under the Plan | 1,500\n"
    "Shares available for future issuance | 500"
)
_FIRING_GEO = "United States | $ | 1,000\nForeign | | 200\nTotal | | 1,200"
_CORE_TABLE = (
    "Deferred tax assets, net | 500\n"
    "Deferred tax liabilities, net | (300)\n"
    "Net deferred tax assets | 200"
)
_CORE_CAPTION = ("Deferred income taxes",)


def _eval(table_text: str, caption_stack=()):
    return evaluate_deferred_tax_separator(
        DeferredTaxSeparatorText(table_text, caption_stack), SPEC
    )


def test_kind_is_declared_as_form_test_data():
    entry = next(
        s
        for s in FORM_TEST_SPECS
        if s.family == FAMILY and s.kind == TEST_DEFERRED_TAX_SEPARATOR
    )
    assert entry.test_id == "deferred_tax_separator"
    assert entry.points == 0.0
    assert entry.provenance == PROV_DEFERRED_TAX_SEPARATOR
    assert SPEC.family == FAMILY
    assert TEST_DEFERRED_TAX_SEPARATOR in profile_for(FAMILY).form_tests


def test_spec_carries_the_priced_stub_data():
    assert "united states" in SPEC.geo_tokens
    assert SPEC.shares_token == "shares"


def test_packet_and_rows_surfaces_agree():
    rows = (
        ("Shares reserved for issuance under the Plan", "1,500"),
        ("Shares available for future issuance", "500"),
    )
    via_rows = evaluate_deferred_tax_separator(
        DeferredTaxSeparatorText.from_rows(rows), SPEC
    )
    via_packet = evaluate_deferred_tax_separator(
        DeferredTaxSeparatorText.from_packet({"table_text": _FIRING_SHARES}),
        SPEC,
    )
    assert via_rows == via_packet
    assert via_rows.fired


def test_recognizer_homes():
    assert _dse.norm_phrase is _tse.norm_phrase
    assert _dse.fired_separator_outcome is _CORE_FORM_OUTCOME


# ---------------- the priced composition ----------------


def test_shares_leg_fires_on_the_priced_shape():
    verdict = _eval(_FIRING_SHARES)
    assert verdict.fired
    assert verdict.legs == ("det_core_absent", "shares_stub")


def test_geo_leg_fires_on_the_priced_shape():
    verdict = _eval(_FIRING_GEO)
    assert verdict.fired
    assert verdict.legs == ("det_core_absent", "geo_stub")


def test_core_present_clears():
    verdict = _eval(_CORE_TABLE, _CORE_CAPTION)
    assert not verdict.fired
    assert deferred_core_present(DeferredTaxSeparatorText(_CORE_TABLE, _CORE_CAPTION))


def test_core_present_clears_despite_a_shares_stub():
    verdict = _eval(_CORE_TABLE + "\nShares outstanding | 100", _CORE_CAPTION)
    assert not verdict.fired


def test_core_absent_without_a_content_leg_clears():
    verdict = _eval("Prepaid expenses | 100\nOther current assets | 200")
    assert not verdict.fired
    assert verdict.evaluable


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


def test_stage_adapter_over_full_grid():
    table = _table(
        (
            ("Shares reserved for issuance under the Plan", "1,500"),
            ("Shares available for future issuance", "500"),
        )
    )
    spec = next(s for s in FORM_TEST_SPECS if s.test_id == "deferred_tax_separator")
    verdict = evaluate_form_test_deferred_tax_separator(table, spec)
    assert verdict.fired
    assert "shares_stub" in verdict.legs


def test_stage_dispatch_stamps_separator_outcome():
    table = _table((("United States", "$", "1,000"), ("Foreign", "", "200")))
    outcomes = {o.test_id: o for o in evaluate_form_tests(table)}
    outcome = outcomes["deferred_tax_separator"]
    assert outcome.kind == TEST_DEFERRED_TAX_SEPARATOR
    assert not outcome.passed and outcome.evaluable
    assert outcome.points == 0.0


# ---------------- competition gate ----------------

_SCORE = {FAMILY: FamilyScore(FAMILY, 11.0, {"signature": 11.0}, ())}


def _outcome(passed: bool, evaluable: bool = True) -> FormTestOutcome:
    return FormTestOutcome(
        FAMILY,
        "deferred_tax_separator",
        TEST_DEFERRED_TAX_SEPARATOR,
        passed,
        evaluable,
        0,
        0.0,
        "separator fired: det_core_absent, shares_stub",
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
