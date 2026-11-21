"""EPS refusal kinds: the precision-p3 packet shapes.
Pins transcribe the priced forms: adjacency (EPS prose,
no EPS rows) and pro-forma (marker plus as-reported row).
"""

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
from edgar_sec.engine.tables.extraction.core.text.context import NoteRef, TableContext
from edgar_sec.engine.tables.extraction.evidence.equity.eps_refusal_evidence import (
    EpsRefusalText,
    evaluate_form_test_eps_adjacency_refusal,
    evaluate_form_test_eps_proforma_refusal,
    legs_for,
)
from edgar_sec.engine.tables.extraction.form_specs.eps_refusal_specs import (
    EPS_REFUSAL_SPECS_BY_TEST_ID,
)
from edgar_sec.engine.tables.extraction.form_specs.form_test_types import (
    FormTestOutcome,
    FormTestSpec,
)
from edgar_sec.engine.tables.extraction.form_tests.form_tests import evaluate_form_tests
from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_scoring import (
    FamilyScore,
)
from edgar_sec.engine.tables.extraction.core.typed_rows import (
    TypedTable,
    structure_table,
)

ADJACENCY_ID = "eps_adjacency_refusal"
SPEC = EPS_REFUSAL_SPECS_BY_TEST_ID[ADJACENCY_ID]
ADJACENCY_SPEC = FormTestSpec("eps_reconciliation", ADJACENCY_ID, ADJACENCY_ID, 0.0)
PROFORMA_ID = "eps_proforma_refusal"
PF_SPEC = EPS_REFUSAL_SPECS_BY_TEST_ID[PROFORMA_ID]
PROFORMA_SPEC = FormTestSpec("eps_reconciliation", PROFORMA_ID, PROFORMA_ID, 0.0)

_PROFORMA_ROWS = (
    ("As reported", "100"),
    ("Pro forma adjustments", "5"),
    ("Pro forma", "105"),
)

_EPS_PROSE = (
    "Options to purchase shares were excluded from the "
    "computation of diluted earnings per share because "
    "they were antidilutive."
)
_ROLLFORWARD_ROWS = (
    ("Balance as of October 31, 2009", "1,000"),
    ("Translation adjustment", "12"),
    ("Balance as of April 30, 2010", "1,012"),
)


def _table(
    rows: tuple[tuple[str, ...], ...],
    *,
    caption_stack: tuple[str, ...] = (),
    prose_before: str = "",
    note: NoteRef | None = None,
) -> TypedTable:
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
        prose_before=prose_before,
        note=note,
    )
    return structure_table(context)


def _legs(table: TypedTable):
    return legs_for(EpsRefusalText.from_table(table, SPEC.prose_tail_chars), SPEC)


def _outcome(table: TypedTable):
    return next(o for o in evaluate_form_tests(table) if o.test_id == ADJACENCY_ID)


def test_adjacency_fires_on_goodwill_shape_identity_absent() -> None:
    table = _table(_ROLLFORWARD_ROWS, prose_before=_EPS_PROSE)
    legs = _legs(table)
    assert legs.prose_eps and not legs.rows_eps_content
    assert legs.identity_absent and legs.adjacency
    outcome = _outcome(table)
    assert outcome.evaluable and not outcome.passed


def test_adjacency_fires_on_inventory_shape_note_other() -> None:
    table = _table(
        (("Raw materials", "300"), ("Finished goods", "700")),
        prose_before=_EPS_PROSE,
        note=NoteRef(3, "Significant Accounting Policies", "Revenue"),
    )
    legs = _legs(table)
    assert legs.note_other and legs.adjacency
    outcome = _outcome(table)
    assert outcome.evaluable and not outcome.passed


def test_adjacency_fires_with_other_named_caption() -> None:
    table = _table(
        _ROLLFORWARD_ROWS,
        caption_stack=("Goodwill and Intangible Assets",),
        prose_before=_EPS_PROSE,
    )
    legs = _legs(table)
    assert legs.caption_other and legs.adjacency


def test_adjacency_silent_on_member_rows() -> None:
    table = _table(
        (
            ("Weighted average common shares outstanding", "1,000"),
            ("Basic earnings per share", "1.00"),
            ("Diluted earnings per share", "0.90"),
        ),
        prose_before="The table reconciles the denominators used "
        "in computing earnings per share.",
    )
    legs = _legs(table)
    assert legs.prose_eps and legs.rows_eps_content
    assert not legs.adjacency
    outcome = _outcome(table)
    assert outcome.evaluable and outcome.passed


def test_adjacency_silent_without_eps_prose() -> None:
    table = _table(
        _ROLLFORWARD_ROWS,
        prose_before="The following table summarizes goodwill by segment.",
    )
    legs = _legs(table)
    assert not legs.prose_eps and not legs.adjacency


def test_adjacency_silent_when_note_names_eps() -> None:
    table = _table(
        _ROLLFORWARD_ROWS,
        prose_before=_EPS_PROSE,
        note=NoteRef(9, "Earnings Per Share", None),
    )
    legs = _legs(table)
    assert not legs.note_other and not legs.identity_absent
    assert not legs.adjacency


def test_adjacency_unevaluable_without_rows() -> None:
    table = _table(())
    result = evaluate_form_test_eps_adjacency_refusal(table, ADJACENCY_SPEC)
    assert not result.evaluable and not result.fired


def _gated_result(passed: bool):
    outcome = FormTestOutcome(
        "eps_reconciliation",
        ADJACENCY_ID,
        ADJACENCY_ID,
        passed,
        True,
        0,
        0.0,
        "adjacency form fired" if not passed else "adjacency form silent",
    )
    geometry = GeometryText(form_tests=(outcome,))
    scores = {
        "eps_reconciliation": FamilyScore(
            "eps_reconciliation", 40.0, {"stub": 40.0}, ()
        )
    }
    return compete(geometry, terms=(), edges=(), scores=scores)


def test_gate_refuses_claim_on_failed_adjacency_outcome() -> None:
    result = _gated_result(passed=False)
    assert "eps_reconciliation" not in result.claims
    trail = result.scores["eps_reconciliation"].evidence
    assert any(e.channel == "gate" for e in trail)


def test_gate_keeps_claim_on_passed_adjacency_outcome() -> None:
    result = _gated_result(passed=True)
    assert result.claims == ("eps_reconciliation",)


def _pf_legs(table: TypedTable):
    return legs_for(EpsRefusalText.from_table(table, PF_SPEC.prose_tail_chars), PF_SPEC)


def _pf_outcome(table: TypedTable):
    return next(o for o in evaluate_form_tests(table) if o.test_id == PROFORMA_ID)


def test_proforma_fires_on_marker_rows_with_as_reported() -> None:
    table = _table(_PROFORMA_ROWS)
    legs = _pf_legs(table)
    assert legs.proforma_hit and legs.as_reported_hit and legs.proforma
    outcome = _pf_outcome(table)
    assert outcome.evaluable and not outcome.passed


def test_proforma_fires_on_prose_marker_with_as_reported() -> None:
    table = _table(
        (("As reported", "100"), ("Adjustments", "5"), ("Total", "105")),
        prose_before="The unaudited pro forma information gives "
        "effect to the acquisition.",
    )
    legs = _pf_legs(table)
    assert legs.proforma_hit and legs.as_reported_hit and legs.proforma


def test_proforma_silent_without_as_reported_row() -> None:
    table = _table(
        (("Pro forma adjustments", "5"), ("Pro forma", "105")),
        prose_before="The unaudited pro forma information follows.",
    )
    legs = _pf_legs(table)
    assert legs.proforma_hit and not legs.as_reported_hit
    assert not legs.proforma
    outcome = _pf_outcome(table)
    assert outcome.evaluable and outcome.passed


def test_proforma_silent_without_marker() -> None:
    table = _table(
        (("As reported", "100"), ("Adjustments", "5"), ("Total", "105")),
        prose_before="The following table presents the results.",
    )
    legs = _pf_legs(table)
    assert not legs.proforma_hit and legs.as_reported_hit
    assert not legs.proforma


def test_proforma_unevaluable_without_rows() -> None:
    table = _table(())
    result = evaluate_form_test_eps_proforma_refusal(table, PROFORMA_SPEC)
    assert not result.evaluable and not result.fired


def _pf_gated_result(passed: bool):
    outcome = FormTestOutcome(
        "eps_reconciliation",
        PROFORMA_ID,
        PROFORMA_ID,
        passed,
        True,
        0,
        0.0,
        "proforma form fired" if not passed else "proforma form silent",
    )
    geometry = GeometryText(form_tests=(outcome,))
    scores = {
        "eps_reconciliation": FamilyScore(
            "eps_reconciliation", 40.0, {"stub": 40.0}, ()
        )
    }
    return compete(geometry, terms=(), edges=(), scores=scores)


def test_gate_refuses_claim_on_failed_proforma_outcome() -> None:
    result = _pf_gated_result(passed=False)
    assert "eps_reconciliation" not in result.claims
    trail = result.scores["eps_reconciliation"].evidence
    assert any(e.channel == "gate" for e in trail)


def test_gate_keeps_claim_on_passed_proforma_outcome() -> None:
    result = _pf_gated_result(passed=True)
    assert result.claims == ("eps_reconciliation",)
