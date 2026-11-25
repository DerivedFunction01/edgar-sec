"""Goodwill foreign-subject separator
(TEST_GOODWILL_FOREIGN_SEPARATOR): conjunction, gate."""

from __future__ import annotations

import edgar_sec.engine.tables.extraction.note_separators.goodwill_foreign_separator_evidence as _gfe
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
    PROV_GOODWILL_FOREIGN_SEPARATOR,
    TEST_GOODWILL_FOREIGN_SEPARATOR,
)
from edgar_sec.engine.tables.extraction.core.subjects.profiles import (
    profile_for,
)
from edgar_sec.engine.tables.extraction.note_separators.goodwill_foreign_separator_evidence import (
    evaluate_form_test_goodwill_foreign_separator,
    evaluate_goodwill_foreign_separator,
)
from edgar_sec.engine.tables.extraction.note_separators.goodwill_foreign_separator_specs import (
    GOODWILL_FOREIGN_SEPARATOR_SPECS,
)
from edgar_sec.engine.tables.extraction.evidence.rollforward_grid_evidence import (
    RollforwardGridText,
)
from edgar_sec.engine.tables.extraction.core.typed_rows import structure_table

SPEC = GOODWILL_FOREIGN_SEPARATOR_SPECS["goodwill_rollforward"]
FAMILY = "goodwill_rollforward"


def _eval(table_text: str, caption: str = ""):
    return evaluate_goodwill_foreign_separator(
        RollforwardGridText(table_text, caption), SPEC
    )


def test_kind_is_declared_as_form_test_data():
    entry = next(
        s
        for s in FORM_TEST_SPECS
        if s.family == FAMILY and s.kind == TEST_GOODWILL_FOREIGN_SEPARATOR
    )
    assert entry.test_id == "goodwill_foreign_separator"
    assert entry.points == 0.0
    assert entry.provenance == PROV_GOODWILL_FOREIGN_SEPARATOR
    assert SPEC.family == FAMILY
    assert TEST_GOODWILL_FOREIGN_SEPARATOR in profile_for(FAMILY).form_tests


def test_spec_carries_the_priced_conjunction():
    legs = [(leg.leg_id, leg.kind, leg.scope) for leg in SPEC.legs]
    assert legs == [
        ("foreign_subject_zone", "foreign_subject_zone", "claim-local"),
        ("goodwill_not_bound", "goodwill_not_bound", "claim-local"),
    ]


def test_recognizer_homes():
    assert _gfe.fired_separator_outcome is _CORE_FORM_OUTCOME


# ---------------- the priced conjunction: kills ----------------

_AVD = (
    "Amount | $\n"
    "Intangible assets at January 1, 2023 | 184,664\n"
    "Additions during fiscal 2023 | 5,000\n"
    "Amortization expense | (12,000)\n"
    "Intangible assets at December 31, 2023 | 177,664"
)


def test_fires_on_intangible_assets_bookends():
    verdict = _eval(_AVD)
    assert verdict.fired
    assert verdict.legs == ("foreign_subject_zone", "goodwill_not_bound")


def test_fires_on_class_enumeration_stubs():
    # header row carries the class columns of the priced form
    text = (
        "Customer relationships | Rare earth quotas | Patents | Trade names"
        " | Land use rights | Other\n"
        "Gross carrying amount | 1,000 | 200 | 300 | 400 | 50 | 10"
    )
    assert _eval(text).fired


def test_fires_on_level3_caption():
    text = (
        "Reconciliation of Level 3 Balances: | \n"
        "Balance 1-1-10 | 500\n"
        "Impairment loss on goodwill | (40)\n"
        "Balance 12-31-10 | 460"
    )
    assert _eval(text, "Reconciliation of Level 3 Balances:").fired


def test_fires_on_statement_page():
    text = (
        "GENEREX BIOTECHNOLOGY CORPORATION AND SUBSIDIARIES | \n"
        "UNAUDITED CONDENSED INTERIM CONSOLIDATED STATEMENTS OF"
        " OPERATIONS | \n"
        "CASH FLOWS FROM OPERATING ACTIVITIES | \n"
        "Net Income | (100)\n"
        "Depreciation and amortization | 20"
    )
    assert _eval(text).fired


def test_fires_on_core_deposit_composition():
    text = (
        "(dollars in thousands) | Gross Carrying Amount | Accumulated"
        " Amortization\n"
        "December 31, 2023 |  | \n"
        "Core deposit | 800 | (300)\n"
        "Customer trust relationships | 600 | (200)\n"
        "Total intangible assets | 1,400 | (500)"
    )
    assert _eval(text).fired


def test_fires_on_single_class_subject():
    text = (
        "Trademark | \n"
        "(Euros in thousands) | \n"
        "Balance as of January 1, 2008 | 24,000\n"
        "Impairment | (2,000)\n"
        "Balance as of December 31, 2008 | 22,000"
    )
    assert _eval(text, "Trademark (Euros in thousands)").fired


def test_fires_on_predominant_combined_with_bare_goodwill_row():
    text = (
        "December 29, | Acquired | Amortization | December 28,\n"
        "(in thousands) | 2013 | Expense | \n"
        "Intangible assets subject to amortization | 834,911 | — | 834,961\n"
        "Accumulated amortization | (394,073) | (58,315) | (452,388)\n"
        "Mastheads | 206,387 | — | 203,587\n"
        "Goodwill | 1,014,257 | — | 1,012,011\n"
        "Total | 1,661,482 | (58,315) | 1,598,171"
    )
    assert _eval(text).fired


# ---------------- the priced conjunction: spares ----------------


def test_clear_on_combined_goodwill_column_walk():
    text = (
        "Total | Goodwill | Other Intangibles\n"
        "Balance as of December 31, 2007 | $ 96,701 | $ 60,849\n"
        "Acquired during the year | 4,000 | 1,000\n"
        "Amortization | — | (2,000)\n"
        "Balance as of June 30, 2008 | 100,701 | 59,849"
    )
    assert not _eval(text).fired


def test_clear_on_segment_walk():
    text = (
        "Aerospace Systems | Electronic Systems | Consolidated Total\n"
        "(in millions) |  | \n"
        "Balance at December 31, 2013 | 3,000 | 4,796\n"
        "Business acquisition | 25 | —\n"
        "Balance at March 28, 2014 | 3,025 | 4,796"
    )
    assert not _eval(text).fired


def test_clear_on_gross_bookend_walk():
    text = (
        "Probe Cards | Systems | Total\n"
        "Goodwill, gross, as of December 26, 2015 | $ 30,731 | $ —\n"
        "Additions - Cascade Microtech acquisition | 5,000 | 1,000\n"
        "Goodwill, gross, as of December 31, 2016 | 35,731 | 1,000"
    )
    assert not _eval(text).fired


def test_clear_on_goodwill_movement_walk():
    text = (
        "Balance at March 31, 2003 | $ 1,788,420\n"
        "Goodwill acquired during the year | 1,265,406\n"
        "Balance at March 31, 2004 | 3,053,826"
    )
    assert not _eval(text).fired


def test_clear_on_caption_bound_goodwill_walk():
    text = (
        "Goodwill | \n"
        "Balance at December 31, 2024 | $ 32,783\n"
        "Adjustment to goodwill acquired in conjunction with acquisition"
        " | 500\n"
        "Balance at March 31, 2025 | 33,283"
    )
    assert not _eval(text, "Goodwill").fired


def test_clear_on_transposed_segment_walk():
    text = (
        "January 1, 2011 | Goodwill Acquired | December 31, 2011\n"
        "Chemicals and Oxides | — | $ 728\n"
        "Magnetic Materials and Alloys | — | 100\n"
        "Rare Metals | — | 50\n"
        "Total | — | 878"
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


_AVD_ROWS = (
    ("Amount",),
    ("Intangible assets at January 1, 2023", "$", "184,664"),
    ("Additions during fiscal 2023", "5,000"),
    ("Amortization expense", "(12,000)"),
    ("Intangible assets at December 31, 2023", "177,664"),
)


def test_stage_adapter_over_full_grid():
    table = _table(_AVD_ROWS)
    spec = next(s for s in FORM_TEST_SPECS if s.test_id == "goodwill_foreign_separator")
    verdict = evaluate_form_test_goodwill_foreign_separator(table, spec)
    assert verdict.fired
    assert "foreign_subject_zone" in verdict.legs


def test_stage_dispatch_stamps_separator_outcome():
    table = _table(_AVD_ROWS)
    outcomes = {o.test_id: o for o in evaluate_form_tests(table)}
    outcome = outcomes["goodwill_foreign_separator"]
    assert outcome.kind == TEST_GOODWILL_FOREIGN_SEPARATOR
    assert not outcome.passed and outcome.evaluable
    assert outcome.points == 0.0


# ---------------- competition gate ----------------

_SCORE = {FAMILY: FamilyScore(FAMILY, 11.0, {"signature": 11.0}, ())}


def _outcome(passed: bool, evaluable: bool = True) -> FormTestOutcome:
    return FormTestOutcome(
        FAMILY,
        "goodwill_foreign_separator",
        TEST_GOODWILL_FOREIGN_SEPARATOR,
        passed,
        evaluable,
        0,
        0.0,
        "foreign separator fired: foreign_subject_zone",
    )


def test_gate_removes_claim_on_fired_outcome():
    geometry = GeometryText(form_tests=(_outcome(False),))
    result = compete(geometry, scores=dict(_SCORE))
    assert FAMILY not in result.claims
    evidence = result.scores[FAMILY].evidence
    assert any(
        item.channel == "gate" and "foreign separator fired" in item.detail
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
