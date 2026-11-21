"""Balance-sheet separator (TEST_BALANCE_SHEET_SEPARATOR): legs, gate."""

from __future__ import annotations

import edgar_sec.engine.tables.extraction.separators.balance_sheet_separator_evidence as _bse
from edgar_sec.engine.tables.ascii_html.model.model import (
    ResolvedGrid,
    TableGeometry,
    TableRenderResult,
)
from edgar_sec.engine.tables.extraction.separators.balance_sheet_separator_evidence import (
    BalanceSheetSeparatorText,
    evaluate_balance_sheet_separator,
    evaluate_form_test_balance_sheet_separator,
    stub_key,
)
from edgar_sec.engine.tables.extraction.separators.balance_sheet_separator_specs import (
    BALANCE_SHEET_SEPARATOR_SPECS,
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
from edgar_sec.engine.tables.extraction.core.subjects.profiles import (
    PROV_BALANCE_SHEET_SEPARATOR,
    TEST_BALANCE_SHEET_SEPARATOR,
    profile_for,
)
from edgar_sec.engine.tables.extraction.core.typed_rows import structure_table
from edgar_sec.foundation.text.dates import (
    STRICT_YEAR_TOKEN_PATTERN as _HOME_STRICT_YEAR,
)
from edgar_sec.engine.tables.numeric_cells import (
    DIGIT_RE as _HOME_DIGIT,
    WRAPPED_NUMERIC_CELL_RE as _HOME_WRAPPED_NUMERIC,
)
from edgar_sec.engine.tables.extraction.pension.pension_routed_evidence import (
    header_keys as _PENSION_HEADER_KEYS,
    norm as _PENSION_NORM,
    stub_key as _PENSION_STUB_KEY,
)
from edgar_sec.engine.tables.extraction.pension.pension_routed_specs import (
    HEADER_STOP_TOKENS as _PENSION_STOP_TOKENS,
    MONTH_TOKENS as _PENSION_MONTH_TOKENS,
)
from edgar_sec.foundation.text.patterns import (
    RE_NON_ALNUM as _HOME_NON_ALNUM,
    RE_WHITESPACE as _HOME_WHITESPACE,
)

SPEC = BALANCE_SHEET_SEPARATOR_SPECS["balance_sheet"]


def _eval(table_text: str):
    return evaluate_balance_sheet_separator(BalanceSheetSeparatorText(table_text), SPEC)


def _grid(header: str, stub: str, rows: int) -> str:
    lines = [header] + [f"{stub} | 100 | 200"] * rows
    return "\n".join(lines)


def test_kind_is_declared_as_form_test_data():
    entry = next(
        s
        for s in FORM_TEST_SPECS
        if s.family == "balance_sheet" and s.kind == TEST_BALANCE_SHEET_SEPARATOR
    )
    assert entry.test_id == "balance_sheet_separator"
    assert entry.points == 0.0
    assert entry.provenance == PROV_BALANCE_SHEET_SEPARATOR
    assert SPEC.family == "balance_sheet"
    assert TEST_BALANCE_SHEET_SEPARATOR in profile_for("balance_sheet").form_tests


def test_packet_and_rows_surfaces_agree():
    rows = (
        ("Total common equity", "100"),
        ("Cash and cash equivalents", "50"),
    )
    via_rows = evaluate_balance_sheet_separator(
        BalanceSheetSeparatorText.from_rows(rows), SPEC
    )
    via_packet = evaluate_balance_sheet_separator(
        BalanceSheetSeparatorText.from_packet(
            {"table_text": "Total common equity | 100\nCash and cash equivalents | 50"}
        ),
        SPEC,
    )
    assert via_rows == via_packet


def test_stub_key_drops_digits_months_and_splits_hyphens():
    assert (
        stub_key("Total other non-current liabilities")
        == "total other non current liabilities"
    )
    assert stub_key("Level 3 assets") == "level assets"
    assert stub_key("Balance at December 31, 2024") == "balance at"


def test_recognizer_homes_and_frozen_text():
    assert _bse.HEADER_STOP_TOKENS is _PENSION_STOP_TOKENS
    assert _bse.MONTH_TOKENS is _PENSION_MONTH_TOKENS
    assert _bse.token_norm is _PENSION_NORM
    assert _bse.stub_key is _PENSION_STUB_KEY
    assert _bse.header_keys is _PENSION_HEADER_KEYS
    assert _bse.RE_NON_ALNUM is _HOME_NON_ALNUM
    assert _bse.RE_WHITESPACE is _HOME_WHITESPACE
    assert _bse.STRICT_YEAR_TOKEN_PATTERN is _HOME_STRICT_YEAR
    assert _bse.HEADER_YEAR_RE.pattern == r"\b(?:19|20)\d{2}\b"
    assert _bse.WRAPPED_NUMERIC_CELL_RE is _HOME_WRAPPED_NUMERIC
    assert _bse.DIGIT_RE is _HOME_DIGIT
    assert _HOME_WRAPPED_NUMERIC.pattern == r"\(?-?\$?\s*\d[\d,]*(?:\.\d+)?\s*\)?\)?"


# ---------------- the ten legs ----------------


def test_leg_year_ladder():
    verdict = _eval(_grid(" | 2021 | 2022 | 2023", "Cash", 14))
    assert "year_ladder" in verdict.legs
    assert "rows_le_12" not in verdict.legs


def test_leg_header_fair():
    verdict = _eval(_grid("Fair value | 2024 | 2023", "Cash", 14))
    assert "hdr:fair" in verdict.legs


def test_leg_header_sheet():
    verdict = _eval(_grid("Balance sheet data | 2024 | 2023", "Cash", 14))
    assert "hdr:sheet" in verdict.legs


def test_leg_stub_total_common_equity():
    text = _grid("Item | 2024 | 2023", "Cash", 13) + "\nTotal common equity | 5 | 6"
    assert "stub:total common equity" in _eval(text).legs


def test_leg_stub_total_other_non_current_liabilities():
    text = (
        _grid("Item | 2024 | 2023", "Cash", 13)
        + "\nTotal other non-current liabilities | 5 | 6"
    )
    assert "stub:total other non current liabilities" in _eval(text).legs


def test_leg_header_issuer():
    verdict = _eval(_grid("Issuer | 2024 | 2023", "Cash", 14))
    assert "hdr:issuer" in verdict.legs


def test_leg_header_funds():
    verdict = _eval(_grid("Funds | 2024 | 2023", "Cash", 14))
    assert "hdr:funds" in verdict.legs


def test_leg_stub_noncurrent_assets():
    text = _grid("Item | 2024 | 2023", "Cash", 13) + "\nNoncurrent assets | 5 | 6"
    assert "stub:noncurrent assets" in _eval(text).legs


def test_leg_numeric_share_below_floor():
    lines = ["Item | alpha | beta"] + ["Label | gamma | delta"] * 13
    verdict = _eval("\n".join(lines))
    assert "numshare_lt_0.3" in verdict.legs


def test_leg_accrued_composition_stub():
    text = (
        _grid("Item | 2024 | 2023", "Cash", 13)
        + "\nAccrued professional services | 5 | 6"
    )
    assert "accrued_stub" in _eval(text).legs
    text = (
        _grid("Item | 2024 | 2023", "Cash", 13) + "\nTotal accrued liabilities | 5 | 6"
    )
    assert "accrued_stub" in _eval(text).legs


def test_plain_balance_sheet_is_clear():
    lines = [
        " | December 31, 2024 | December 31, 2023",
        "Cash and cash equivalents | 100 | 90",
        "Accounts receivable, net | 200 | 180",
        "Inventories | 300 | 280",
        "Prepaid expenses | 40 | 35",
        "Total current assets | 640 | 585",
        "Property and equipment, net | 500 | 470",
        "Goodwill | 150 | 150",
        "Other assets | 60 | 55",
        "Total assets | 1350 | 1260",
        "Accounts payable | 120 | 110",
        "Accrued expenses | 80 | 75",
        "Current portion of long-term debt | 50 | 45",
        "Total current liabilities | 250 | 230",
        "Long-term debt | 400 | 420",
        "Other liabilities | 70 | 65",
        "Total liabilities | 720 | 715",
        "Common stock | 10 | 10",
        "Retained earnings | 620 | 535",
        "Total stockholders' equity | 630 | 545",
        "Total liabilities and stockholders' equity | 1350 | 1260",
    ]
    verdict = _eval("\n".join(lines))
    assert not verdict.fired
    assert verdict.legs == ()


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
    table = _table((("Cash", "100"), ("Total common equity", "50")))
    spec = next(s for s in FORM_TEST_SPECS if s.test_id == "balance_sheet_separator")
    verdict = evaluate_form_test_balance_sheet_separator(table, spec)
    assert verdict.fired
    assert "stub:total common equity" in verdict.legs


def test_stage_dispatch_stamps_separator_outcome():
    table = _table((("Cash", "100"), ("Total common equity", "50")))
    outcomes = {o.test_id: o for o in evaluate_form_tests(table)}
    outcome = outcomes["balance_sheet_separator"]
    assert outcome.kind == TEST_BALANCE_SHEET_SEPARATOR
    assert not outcome.passed and outcome.evaluable
    assert outcome.points == 0.0


# ---------------- competition gate ----------------

_SCORE = {"balance_sheet": FamilyScore("balance_sheet", 11.0, {"signature": 11.0}, ())}


def _outcome(passed: bool, evaluable: bool = True) -> FormTestOutcome:
    return FormTestOutcome(
        "balance_sheet",
        "balance_sheet_separator",
        TEST_BALANCE_SHEET_SEPARATOR,
        passed,
        evaluable,
        0,
        0.0,
        "separator fired: rows_le_12",
    )


def test_gate_removes_claim_on_fired_outcome():
    geometry = GeometryText(form_tests=(_outcome(False),))
    result = compete(geometry, scores=dict(_SCORE))
    assert "balance_sheet" not in result.claims
    evidence = result.scores["balance_sheet"].evidence
    assert any(
        item.channel == "gate" and "separator fired" in item.detail for item in evidence
    )


def test_gate_keeps_claim_on_clear_outcome():
    geometry = GeometryText(form_tests=(_outcome(True),))
    result = compete(geometry, scores=dict(_SCORE))
    assert "balance_sheet" in result.claims


def test_gate_keeps_claim_when_outcome_absent():
    result = compete(GeometryText(), scores=dict(_SCORE))
    assert "balance_sheet" in result.claims


def test_gate_keeps_claim_when_outcome_unevaluable():
    geometry = GeometryText(form_tests=(_outcome(False, evaluable=False),))
    result = compete(geometry, scores=dict(_SCORE))
    assert "balance_sheet" in result.claims
