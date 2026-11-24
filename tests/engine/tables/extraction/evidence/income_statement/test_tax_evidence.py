"""Tax seat: registry data, the priced conjunction, the seat."""

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
from edgar_sec.engine.tables.extraction.specs.families.tax_evidence_specs import (
    TAX_EVIDENCE_SPECS,
    TAX_EVIDENCE_SPECS_BY_TEST_ID,
)
from edgar_sec.engine.tables.extraction.core.subjects.profile_constants import (
    TEST_TAX_EVIDENCE,
)
from edgar_sec.engine.tables.extraction.core.subjects.profiles import (
    profile_for,
)
from edgar_sec.engine.tables.extraction.core.subjects.signature_profiles import (
    SignatureTerm,
)
from edgar_sec.engine.tables.extraction.evidence.income_statement.tax_evidence import (
    TaxText,
    evaluate_form_test_tax,
    evaluate_tax_evidence,
)
from edgar_sec.engine.tables.extraction.core.typed_rows import structure_table

SPEC = TAX_EVIDENCE_SPECS["tax_reconciliation"]


def _table(rows: tuple[tuple[str, ...], ...], prose_before: str = ""):
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
    context = TableContext(geometry=geometry, prose_before=prose_before)
    return structure_table(context)


def _passed_outcome(passed: bool = True) -> FormTestOutcome:
    return FormTestOutcome(
        family="tax_reconciliation",
        test_id=SPEC.test_id,
        kind=TEST_TAX_EVIDENCE,
        passed=passed,
        evaluable=True,
        columns_closed=0,
        points=0.0,
        detail="anchor 'statutory' in stub; context 'tax' in lead",
    )


def test_seat_is_declared_as_form_test_data():
    seat_id = "tax_reconciliation_statutory_anchor_seat"
    entry = next(s for s in FORM_TEST_SPECS if s.test_id == seat_id)
    assert entry.family == "tax_reconciliation"
    assert entry.kind == TEST_TAX_EVIDENCE
    assert entry.points == 0.0
    assert TAX_EVIDENCE_SPECS_BY_TEST_ID[entry.test_id] is SPEC
    assert SPEC.seat_veto_precedence_terms == ("ended march",)
    assert TEST_TAX_EVIDENCE in profile_for("tax_reconciliation").form_tests


def test_both_legs_admit():
    verdict = evaluate_tax_evidence(
        TaxText(
            stub_text="income tax expense at statutory rate state taxes",
            lead_text="the provision for income taxes consists of",
        ),
        SPEC,
    )
    assert verdict.admitted


def test_anchor_alone_refuses():
    verdict = evaluate_tax_evidence(
        TaxText(
            stub_text="income tax expense at statutory rate",
            lead_text="the following table summarizes the components",
        ),
        SPEC,
    )
    assert not verdict.admitted
    assert "lead" in verdict.detail


def test_context_alone_refuses():
    verdict = evaluate_tax_evidence(
        TaxText(
            stub_text="income tax expense state and local",
            lead_text="the provision for income taxes consists of",
        ),
        SPEC,
    )
    assert not verdict.admitted
    assert "stub" in verdict.detail


def test_anchor_in_lead_does_not_count():
    verdict = evaluate_tax_evidence(
        TaxText(
            stub_text="income tax expense state and local",
            lead_text="reconciled at the statutory rate, income taxes were",
        ),
        SPEC,
    )
    assert not verdict.admitted


def test_context_is_a_substring_test_as_priced():
    verdict = evaluate_tax_evidence(
        TaxText(
            stub_text="at the statutory federal rate",
            lead_text="deferred taxes and taxes payable are",
        ),
        SPEC,
    )
    assert verdict.admitted


def test_stage_adapter_over_full_grid():
    rows = (
        ("", "2024", "2023"),
        ("Income tax at statutory rate", "21.0%", "21.0%"),
        ("State taxes, net", "4.1%", "3.8%"),
        ("Effective rate", "25.1%", "24.8%"),
    )
    spec = next(s for s in FORM_TEST_SPECS if s.test_id == SPEC.test_id)
    admitted = evaluate_form_test_tax(
        _table(rows, "Income taxes. The provision for income taxes follows:"),
        spec,
    )
    assert admitted.admitted
    refused = evaluate_form_test_tax(
        _table(rows, "The following table presents the components:"),
        spec,
    )
    assert not refused.admitted


def test_seat_claims_unclaimed_geometry_at_the_floor():
    geometry = GeometryText(
        stubs=("Reconciling items", "Other adjustments"),
        form_tests=(_passed_outcome(),),
    )
    result = compete(geometry, terms=())
    assert result.claims == ("tax_reconciliation",)
    group = result.groups[0]
    assert group.state == "claimed" and group.score >= 5.0
    seated = result.scores["tax_reconciliation"]
    assert any(item.channel == "gate" for item in seated.evidence)


def test_seat_sits_beside_an_existing_claim():
    terms = (
        SignatureTerm("goodwill", "stub", "goodwill", 4.0, 5, 0),
        SignatureTerm("goodwill", "stub", "intangible assets", 4.0, 5, 0),
    )
    geometry = GeometryText(
        stubs=("Goodwill", "Intangible assets"),
        form_tests=(_passed_outcome(),),
    )
    result = compete(geometry, terms=terms)
    assert result.claims == ("goodwill", "tax_reconciliation")


def test_no_seat_without_a_passed_outcome():
    geometry = GeometryText(
        stubs=("Reconciling items", "Other adjustments"),
        form_tests=(_passed_outcome(passed=False),),
    )
    assert compete(geometry, terms=()).claims == ()
    bare = GeometryText(stubs=("Reconciling items", "Other adjustments"))
    assert compete(bare, terms=()).claims == ()


def test_hard_veto_bars_the_seat():
    geometry = GeometryText(
        stubs=("Income tax at statutory rate", "Total"),
        grid_text="Income tax at statutory rate Total",
        form_tests=(_passed_outcome(),),
    )
    result = compete(geometry, terms=())
    assert "tax_reconciliation" not in result.claims


_TAX_TERMS = (
    SignatureTerm("tax_reconciliation", "stub", "reconciling items", 4.0, 5, 0),
    SignatureTerm("tax_reconciliation", "stub", "other adjustments", 4.0, 5, 0),
)


def test_seat_displaces_the_scored_claim_when_it_does_not_fire():
    geometry = GeometryText(
        stubs=("Reconciling items", "Other adjustments"),
        form_tests=(_passed_outcome(passed=False),),
    )
    assert compete(geometry, terms=_TAX_TERMS).claims == ()
    bare = GeometryText(stubs=("Reconciling items", "Other adjustments"))
    assert compete(bare, terms=_TAX_TERMS).claims == ()


def test_seat_replaces_the_scored_claim_with_its_own():
    geometry = GeometryText(
        stubs=("Reconciling items", "Other adjustments"),
        form_tests=(_passed_outcome(),),
    )
    result = compete(geometry, terms=_TAX_TERMS)
    assert result.claims == ("tax_reconciliation",)
    trail = result.scores["tax_reconciliation"].evidence
    assert any(item.channel == "gate" and "displaces" in item.detail for item in trail)


def test_seat_outranks_the_ended_march_lead_veto():
    geometry = GeometryText(
        stubs=("Income tax at statutory rate", "State taxes, net"),
        lead="income taxes for the three months ended march 31, 2013",
        form_tests=(_passed_outcome(),),
    )
    result = compete(geometry, terms=())
    assert result.claims == ("tax_reconciliation",)


def test_months_ended_alone_still_bars_the_seat():
    geometry = GeometryText(
        stubs=("Income tax at statutory rate", "State taxes, net"),
        lead="income taxes for the six months ended june 30, 2013",
        form_tests=(_passed_outcome(),),
    )
    result = compete(geometry, terms=())
    assert "tax_reconciliation" not in result.claims


def test_an_earlier_recorded_term_still_bars_the_seat():
    geometry = GeometryText(
        stubs=("Income tax at statutory rate", "State taxes, net"),
        lead="revenue detail for the period ended march 31, 2013",
        form_tests=(_passed_outcome(),),
    )
    result = compete(geometry, terms=())
    assert "tax_reconciliation" not in result.claims
