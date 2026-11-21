"""Pension routed separator (TEST_PENSION_ROUTED): registry, form, gate."""

from __future__ import annotations

from edgar_sec.engine.tables.ascii_html.model import (
    ResolvedGrid,
    TableGeometry,
    TableRenderResult,
)
from edgar_sec.engine.tables.extraction.cascade.competition import compete
from edgar_sec.engine.tables.extraction.cascade.geometry_text import GeometryText
from edgar_sec.engine.tables.extraction.core.context import TableContext
from edgar_sec.engine.tables.extraction.form_specs.form_test_specs import (
    FORM_TEST_SPECS,
)
from edgar_sec.engine.tables.extraction.form_specs.form_test_types import (
    FormTestOutcome,
)
from edgar_sec.engine.tables.extraction.form_tests.form_tests import evaluate_form_tests
from edgar_sec.engine.tables.extraction.cascade.geometry_scoring import FamilyScore
import edgar_sec.engine.tables.extraction.pension.pension_routed_evidence as _pre
from edgar_sec.engine.tables.extraction.pension.pension_routed_evidence import (
    PensionRoutedText,
    evaluate_form_test_pension_routed,
    evaluate_pension_routed,
    header_keys,
    norm,
    stub_key,
)
from edgar_sec.engine.tables.extraction.core.profiles import (
    PROV_PENSION_ROUTED,
    TEST_PENSION_ROUTED,
    profile_for,
)
from edgar_sec.engine.tables.extraction.core.typed_rows import structure_table


def _eval(table_text: str, caption_stack=()):
    return evaluate_pension_routed(PensionRoutedText(table_text, caption_stack))


def test_kind_is_declared_as_form_test_data():
    entry = next(
        s
        for s in FORM_TEST_SPECS
        if s.family == "pension" and s.kind == TEST_PENSION_ROUTED
    )
    assert entry.test_id == "pension_routed_separator"
    assert entry.points == 0.0
    assert entry.provenance == PROV_PENSION_ROUTED
    assert TEST_PENSION_ROUTED in profile_for("pension").form_tests


def test_norm_is_the_priced_norm():
    assert norm("  Service Cost: $1,000 ") == "service cost 1 000"
    assert norm("") == "" and norm(None) == ""


def test_stub_key_drops_digits_months_and_truncates():
    assert stub_key("Service cost 2024") == "service cost"
    assert stub_key("Balance at December 31, 2024") == "balance at"


def test_read_header_features_come_from_the_homed_derivation():
    read = _pre._read(PensionRoutedText("Funded status of the plan | 2024 | 2023"))
    hdr_features = {f for f in read.features if f.startswith("hdr:")}
    expected = {
        f"hdr:{k}" for k in header_keys(("Funded status of the plan", "2024", "2023"))
    }
    assert hdr_features == expected


def test_packet_and_rows_surfaces_agree():
    rows = (
        ("Service cost", "10"),
        ("Interest cost", "20"),
    )
    via_rows = evaluate_pension_routed(PensionRoutedText.from_rows(rows, ()))
    via_packet = evaluate_pension_routed(
        PensionRoutedText.from_packet(
            {
                "table_text": "Service cost | 10\nInterest cost | 20",
                "caption_stack": [],
            }
        )
    )
    assert via_rows == via_packet


# ---------------- routed kind cells ----------------


def test_cost_cell_kills_on_rows_leg():
    verdict = _eval("Service cost | 10\nInterest cost | 20\nTotal | 30")
    assert not verdict.admitted
    assert verdict.detail == "kind:cost cell fired (A:rows_le_5)"


def test_cost_cell_clear_when_large_and_moving():
    lines = [
        "Service cost | 10",
        "Interest cost | 20",
        "Contributions | 5",
        "Distributions | 4",
        "Settlements | 3",
        "Purchases | 2",
        "Transfers | 1",
        "Other | 0",
    ]
    verdict = _eval("\n".join(lines))
    assert verdict.admitted
    assert verdict.detail == "kind:cost clear"


def test_walk_cell_kills_without_bookend_begin():
    verdict = _eval("Change in benefit obligation | 5\nBenefits paid | 3\nOther | 1")
    assert not verdict.admitted
    assert verdict.detail == "kind:walk cell fired (B:bookend_begin)"


def test_walk_cell_clear_with_bookend_begin():
    verdict = _eval(
        "Change in benefit obligation | 5\n"
        "Benefit obligation at beginning of year | 100\n"
        "Benefits paid | 3"
    )
    assert verdict.admitted
    assert verdict.detail == "kind:walk clear"


def test_funded_cell_kills_on_header_token():
    verdict = _eval(
        "Three months ended | 2024 | 2023\nFunded status | 5\n"
        "Accumulated benefit obligation | 7"
    )
    assert not verdict.admitted
    assert verdict.detail == "kind:funded cell fired (A:hdr:three)"


def test_assumptions_cell_kills_on_millions_header():
    verdict = _eval("Millions of dollars | x\nDiscount rate | 5\nWeighted average | 6")
    assert not verdict.admitted
    assert verdict.detail == "kind:assumptions cell fired (A:hdr:millions of dollars)"


def test_assets_cell_share_threshold():
    rich = _eval(
        "Equity securities | 10\nFixed income | 8\nDebt securities | 6\n"
        "Real estate | 4\nTotal | 28"
    )
    assert rich.admitted
    assert rich.detail == "kind:assets clear"
    poor = _eval(
        "Equity securities | 10\nFixed income | 8\nMoney market | 6\n"
        "Cash equivalents | 4\nOther | 2"
    )
    assert not poor.admitted
    assert poor.detail == "kind:assets cell fired (core_share<0.5 of strong)"


def test_payments_cell_kills_when_no_surface_hit():
    verdict = _eval(
        "Expected 2025 contributions | 5\nEstimated 2026 employer contributions | 6"
    )
    assert not verdict.admitted
    assert verdict.detail == "kind:payments allsurf_xboth fired"


def test_payments_cell_clear_on_surface_hit():
    verdict = _eval("Estimated future benefit payments | 5\nThereafter | 9")
    assert verdict.admitted
    assert verdict.detail == "kind:payments allsurf_xboth clear"


def test_payments_cell_clear_on_year_ladder():
    verdict = _eval(
        "Estimated future benefit payments | 5\n2026 | 1\n2027 | 2\n2028 | 3\n2029 | 4"
    )
    assert verdict.admitted
    assert verdict.detail == "kind:payments allsurf_xboth clear"


# ---------------- undetermined: increment, seg, ext, abstain ----------------


def test_increment_cap_payments_due():
    verdict = _eval("Rent expense | 5\nUtilities | 3", ("Payments due under the plan",))
    assert not verdict.admitted
    assert verdict.detail == "inc:cap_payments_due (host commitments_contingencies)"


def test_increment_host2_supp():
    verdict = _eval("Operating lease obligations | 5\nTotal | 9\nRent expense | 3")
    assert not verdict.admitted
    assert verdict.detail == "inc:host2_supp (host commitments_contingencies)"


def test_increment_hdr_item201d():
    verdict = _eval(
        "Shares to be issued upon exercise | options\nOptions outstanding | 5\n"
        "Shares available | 3"
    )
    assert not verdict.admitted
    assert verdict.detail == "inc:hdr_item201d (host stock_comp_rollforward)"


def test_seg_leg_kills_on_raw_stub_multiplicity():
    verdict = _eval("United States | 10\nUnited States | 20\nUnited States | 30")
    assert not verdict.admitted
    assert verdict.detail == "seg:seg_raw3"


def test_seg_leg_never_fires_on_routed_specimens():
    packet = "Service cost | 1\nInterest cost | 2\nService cost | 3\nService cost | 4"
    verdict = _eval(packet)
    assert verdict.detail == "kind:cost cell fired (A:rows_le_5)"


def test_ext_route_applies_payments_cell_and_admits():
    verdict = _eval("Pension benefits | x\nApples | 5\nOranges | 3")
    assert verdict.admitted
    assert verdict.detail == "ext:benefit_hdr allsurf_xboth clear"


def test_abstain_admits_undetermined():
    verdict = _eval("Apples | 5\nOranges | 3")
    assert verdict.admitted
    assert verdict.detail == "abstain"


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
    table = _table((("Service cost", "10"), ("Interest cost", "20")))
    spec = next(s for s in FORM_TEST_SPECS if s.test_id == "pension_routed_separator")
    verdict = evaluate_form_test_pension_routed(table, spec)
    assert not verdict.admitted
    outcomes = {o.test_id: o for o in evaluate_form_tests(table)}
    outcome = outcomes["pension_routed_separator"]
    assert outcome.kind == TEST_PENSION_ROUTED
    assert not outcome.passed and outcome.evaluable
    assert outcome.points == 0.0


# ---------------- competition gate ----------------

_SCORE = {"pension": FamilyScore("pension", 11.0, {"signature": 11.0}, ())}
_ANCHOR_STUBS = ("Service cost", "Interest cost", "Expected return", "Total")


def _outcome(passed: bool, evaluable: bool = True) -> FormTestOutcome:
    return FormTestOutcome(
        "pension",
        "pension_routed_separator",
        TEST_PENSION_ROUTED,
        passed,
        evaluable,
        0,
        0.0,
        "kind:cost cell fired (A:rows_le_5)",
    )


def test_gate_removes_claim_on_failed_outcome():
    geometry = GeometryText(stubs=_ANCHOR_STUBS, form_tests=(_outcome(False),))
    result = compete(geometry, scores=dict(_SCORE))
    assert "pension" not in result.claims
    evidence = result.scores["pension"].evidence
    assert any(
        item.channel == "gate" and "kind:cost" in item.detail for item in evidence
    )


def test_gate_keeps_claim_on_passed_outcome():
    geometry = GeometryText(stubs=_ANCHOR_STUBS, form_tests=(_outcome(True),))
    result = compete(geometry, scores=dict(_SCORE))
    assert "pension" in result.claims


def test_gate_keeps_claim_when_outcome_absent():
    geometry = GeometryText(stubs=_ANCHOR_STUBS)
    result = compete(geometry, scores=dict(_SCORE))
    assert "pension" in result.claims


def test_gate_keeps_claim_when_outcome_unevaluable():
    geometry = GeometryText(
        stubs=_ANCHOR_STUBS, form_tests=(_outcome(False, evaluable=False),)
    )
    result = compete(geometry, scores=dict(_SCORE))
    assert "pension" in result.claims
