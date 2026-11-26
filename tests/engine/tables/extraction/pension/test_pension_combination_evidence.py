"""Pension combination separator (TEST_PENSION_COMBINATION): registry, legs, gate."""

from __future__ import annotations

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
from edgar_sec.engine.tables.extraction.pension.pension_combination_evidence import (
    PensionCombinationText,
    evaluate_form_test_pension_combination,
    evaluate_pension_combination,
)
from edgar_sec.engine.tables.extraction.core.subjects.profile_constants import (
    PROV_PENSION_COMBINATION,
    TEST_PENSION_COMBINATION,
)
from edgar_sec.engine.tables.extraction.core.subjects.profiles import (
    profile_for,
)
from edgar_sec.engine.tables.extraction.core.typed_rows import structure_table


def _eval(table_text: str, caption_stack=()):
    return evaluate_pension_combination(
        PensionCombinationText(table_text, caption_stack)
    )


def test_kind_is_declared_as_form_test_data():
    entry = next(
        s
        for s in FORM_TEST_SPECS
        if s.family == "pension" and s.kind == TEST_PENSION_COMBINATION
    )
    assert entry.test_id == "pension_combination_separator"
    assert entry.points == 0.0
    assert entry.provenance == PROV_PENSION_COMBINATION
    assert TEST_PENSION_COMBINATION in profile_for("pension").form_tests


def test_packet_and_rows_surfaces_agree():
    rows = (
        ("Balance at December 31, 2024", "5"),
        ("Apples", "3"),
        ("Oranges", "2"),
        ("Pears", "1"),
    )
    via_rows = evaluate_pension_combination(PensionCombinationText.from_rows(rows, ()))
    via_packet = evaluate_pension_combination(
        PensionCombinationText.from_packet(
            {
                "table_text": (
                    "Balance at December 31, 2024 | 5\nApples | 3\n"
                    "Oranges | 2\nPears | 1"
                ),
                "caption_stack": [],
            }
        )
    )
    assert via_rows == via_packet


# ---------------- priced leg cells ----------------


def test_rows_leg_kills_at_two_rows():
    verdict = _eval("Apples | 5\nOranges | 3")
    assert not verdict.admitted
    assert verdict.detail == "rows_le_2"


def test_rows_leg_carries_no_core_condition():
    verdict = _eval("Service cost | 10\nInterest cost | 20")
    assert not verdict.admitted
    assert verdict.detail == "rows_le_2"


def test_core_present_clears_the_gated_legs():
    verdict = _eval("Service cost | 10\nInterest cost | 20\nTotal | 30")
    assert verdict.admitted
    assert verdict.detail == "clear"


def test_revenue_stub_leg_kills():
    verdict = _eval("Net sales | 100\nCost of sales | 60\nGross margin | 40")
    assert not verdict.admitted
    assert verdict.detail == "revenue_stub"


def test_host_leg_kills_on_balance_at_key():
    verdict = _eval(
        "Balance at December 31, 2024 | 5\nApples | 3\nOranges | 2\nPears | 1"
    )
    assert not verdict.admitted
    assert verdict.detail == "host_stubkey (host aoci_rollforward)"


_LADDER_ROWS = [f"{year} | 10 | 4" for year in range(2024, 2029)]


def test_host_leg_yields_to_the_benefit_payments_ladder():
    rows = [" | Pension Benefits | Post-Retirement Medical Benefits"]
    rows += _LADDER_ROWS
    rows += ["Thereafter | 50 | 20", "Total | 100 | 40"]
    verdict = _eval("\n".join(rows))
    assert verdict.admitted
    assert verdict.detail == "clear"


def test_host_leg_holds_without_benefit_terms():
    rows = [" | Amount"] + _LADDER_ROWS
    rows += ["Thereafter | 50 | 20", "Total | 100 | 40"]
    verdict = _eval("\n".join(rows))
    assert not verdict.admitted
    assert verdict.detail == "host_stubkey (host debt_maturity)"


def test_host_leg_holds_without_the_year_ladder():
    verdict = _eval(" | Pension Benefits\nThereafter | 50\nTotal | 100\nApples | 3")
    assert not verdict.admitted
    assert verdict.detail == "host_stubkey (host debt_maturity)"


def test_guarantee_leg_kills_when_stub_surface_is_empty():
    verdict = _eval(
        "| Guarantees with customers | 5\n| Guarantees - other | 3\n"
        "| Total guarantees | 8\n| Other | 1"
    )
    assert not verdict.admitted
    assert verdict.detail == "guarantee_offset"


def test_offset_candidate_leg_kills_on_cc_token():
    verdict = _eval(
        "| Lease payments due | 5 | 6 | 7\n| Operating lease | 3 | 2 | 1\n"
        "| Total | 8 | 8 | 8\n| Other | 1 | 1 | 1"
    )
    assert not verdict.admitted
    assert verdict.detail == "offset_candidate"


def test_cc_hdr_leg_kills_on_two_header_hits():
    verdict = _eval(
        "Total payments due | 2024 | 2025\nApples | 5 | 6\n"
        "Oranges | 3 | 4\nPears | 2 | 1"
    )
    assert not verdict.admitted
    assert verdict.detail == "cc_hdr_ge2"


def test_no_leg_fires_admits():
    verdict = _eval("Apples | 5\nOranges | 3\nPears | 2\nGrapes | 1")
    assert verdict.admitted
    assert verdict.detail == "clear"


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
        geometry=geometry,
        caption_stack=caption_stack,
        prose_before="",
    )
    return structure_table(context)


def test_stage_adapter_and_dispatch_stamp_outcome():
    table = _table(
        (
            ("Balance at December 31, 2024", "5"),
            ("Apples", "3"),
            ("Oranges", "2"),
            ("Pears", "1"),
        )
    )
    spec = next(
        s for s in FORM_TEST_SPECS if s.test_id == "pension_combination_separator"
    )
    verdict = evaluate_form_test_pension_combination(table, spec)
    assert not verdict.admitted
    outcomes = {o.test_id: o for o in evaluate_form_tests(table)}
    outcome = outcomes["pension_combination_separator"]
    assert outcome.kind == TEST_PENSION_COMBINATION
    assert not outcome.passed and outcome.evaluable
    assert outcome.points == 0.0


# ---------------- competition gate ----------------

_SCORE = {"pension": FamilyScore("pension", 11.0, {"signature": 11.0}, ())}
_ANCHOR_STUBS = ("Service cost", "Interest cost", "Expected return", "Total")


def _outcome(passed: bool, evaluable: bool = True) -> FormTestOutcome:
    return FormTestOutcome(
        "pension",
        "pension_combination_separator",
        TEST_PENSION_COMBINATION,
        passed,
        evaluable,
        0,
        0.0,
        "rows_le_2",
    )


def test_gate_removes_claim_on_failed_outcome():
    geometry = GeometryText(stubs=_ANCHOR_STUBS, form_tests=(_outcome(False),))
    result = compete(geometry, scores=dict(_SCORE))
    assert "pension" not in result.claims
    evidence = result.scores["pension"].evidence
    assert any(
        item.channel == "gate" and "rows_le_2" in item.detail for item in evidence
    )


def test_gate_keeps_claim_on_passed_outcome():
    geometry = GeometryText(
        data_rows=1, stubs=_ANCHOR_STUBS, form_tests=(_outcome(True),)
    )
    result = compete(geometry, scores=dict(_SCORE))
    assert "pension" in result.claims


def test_gate_keeps_claim_when_outcome_absent():
    geometry = GeometryText(data_rows=1, stubs=_ANCHOR_STUBS)
    result = compete(geometry, scores=dict(_SCORE))
    assert "pension" in result.claims


def test_gate_keeps_claim_when_outcome_unevaluable():
    geometry = GeometryText(
        data_rows=1, stubs=_ANCHOR_STUBS, form_tests=(_outcome(False, evaluable=False),)
    )
    result = compete(geometry, scores=dict(_SCORE))
    assert "pension" in result.claims
