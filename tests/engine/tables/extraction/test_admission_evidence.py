"""Admission evidence: the priced J1 and JOINT reads."""

from __future__ import annotations

from edgar_sec.engine.tables.ascii_html.model import (
    ResolvedGrid,
    TableGeometry,
    TableRenderResult,
)
from edgar_sec.engine.tables.extraction.admission_evidence import (
    evaluate_commitments_joint,
    evaluate_debt_admission,
    ladder_reconciles,
)
from edgar_sec.engine.tables.extraction.assembly import _seat_joint_evidence
from edgar_sec.engine.tables.extraction.classify import (
    Classification,
    Evidence,
    TableKind,
)
from edgar_sec.engine.tables.extraction.competition import (
    CLAIM_FLOOR,
    FamilyScore,
    GeometryText,
    compete,
)
from edgar_sec.engine.tables.extraction.context import TableContext
from edgar_sec.engine.tables.extraction.form_test_specs import (
    FormTestOutcome,
    form_test_specs_for,
)
from edgar_sec.engine.tables.extraction.form_tests import evaluate_form_tests
from edgar_sec.engine.tables.extraction.profiles import (
    PROFILES_BY_FAMILY,
    PROV_STEP7_PRICING,
    TEST_ADMISSION_EVIDENCE,
)
from edgar_sec.engine.tables.extraction.registry import (
    ASSIGNMENT_FLOOR,
    RESIDUAL_FAMILY,
)
from edgar_sec.engine.tables.extraction.typed_rows import TypedTable, structure_table

_LADDER_ROWS = (
    ("", "Amount"),
    ("2027", "100"),
    ("2028", "200"),
    ("2029", "300"),
    ("Total", "600"),
)
_PERIOD_ROWS = (
    ("", "Total", "Less than 1 Year", "1-3 Years", "3-5 Years", "More than 5 Years"),
    ("Purchase obligations", "900", "300", "300", "200", "100"),
    ("Operating leases", "500", "100", "200", "100", "100"),
)
_DEBT_PROSE = (
    "The following is a summary of the maturities of our long-term "
    "debt: aggregate principal payments due in each period."
)


def _table(
    rows: tuple[tuple[str, ...], ...],
    *,
    caption_stack: tuple[str, ...] = (),
    prose_before: str = "",
) -> TypedTable:
    geometry = TableGeometry(
        table_index=0,
        render_result=TableRenderResult(
            ascii_text="",
            resolved_grid=ResolvedGrid(
                rows=rows, column_alignments=(), column_widths=(), header_row_count=0
            ),
            confidence=1.0,
        ),
    )
    context = TableContext(
        geometry=geometry,
        caption_stack=caption_stack,
        prose_before=prose_before,
    )
    return structure_table(context)


def test_j1_passes_on_the_priced_gold_shape() -> None:
    outcome = evaluate_debt_admission(_table(_LADDER_ROWS, prose_before=_DEBT_PROSE))
    assert outcome.passed
    assert outcome.recon


def test_j1_needs_the_prose_subject() -> None:
    table = _table(_LADDER_ROWS, prose_before="Supplemental information follows.")
    assert not evaluate_debt_admission(table).passed


def test_j1_needs_the_ladder() -> None:
    rows = (("Cash and equivalents", "500"), ("Total assets", "900"))
    table = _table(rows, prose_before=_DEBT_PROSE)
    assert not evaluate_debt_admission(table).passed


def test_j1_subject_reads_the_matur_stem() -> None:
    # The priced specimen's prose spells the stem without the
    # full "maturit" substring; the priced D1 reads "matur".
    prose = "Debt maturing in future periods, by borrowing, is summarized below."
    outcome = evaluate_debt_admission(_table(_LADDER_ROWS, prose_before=prose))
    assert outcome.passed


def test_recon_reads_the_column_axis() -> None:
    rows = (
        ("", "Total", "2027", "2028", "2029"),
        ("Debt obligations", "600", "100", "200", "300"),
    )
    assert ladder_reconciles(_table(rows))


def test_recon_rejects_a_total_the_steps_do_not_sum_to() -> None:
    rows = (
        ("", "Total", "2027", "2028", "2029"),
        ("Debt obligations", "650", "100", "200", "300"),
    )
    assert not ladder_reconciles(_table(rows))


def test_joint_passes_on_the_period_subform() -> None:
    table = _table(_PERIOD_ROWS, caption_stack=("Commitments and Contingencies",))
    assert evaluate_commitments_joint(table).passed


def test_joint_passes_on_the_credit_subform() -> None:
    rows = (
        ("Commitments to extend credit", "1,000"),
        ("Standby letters of credit", "250"),
    )
    table = _table(rows, caption_stack=("Commitments",))
    assert evaluate_commitments_joint(table).passed


def test_joint_needs_the_heading_subject() -> None:
    table = _table(_PERIOD_ROWS, caption_stack=("Note 12 — Other Liabilities",))
    assert not evaluate_commitments_joint(table).passed


def test_joint_needs_a_subform() -> None:
    rows = (("Accrued expenses", "400"), ("Other current liabilities", "50"))
    table = _table(rows, caption_stack=("Commitments and Contingencies",))
    assert not evaluate_commitments_joint(table).passed


def test_admission_specs_are_zero_point_registry_data() -> None:
    for family, test_id in (
        ("debt_maturity", "debt_maturity_j1_admission"),
        ("commitments_contingencies", "commitments_joint_admission"),
    ):
        spec = next(s for s in form_test_specs_for(family) if s.test_id == test_id)
        assert spec.kind == TEST_ADMISSION_EVIDENCE
        assert spec.points == 0.0
        assert spec.provenance == PROV_STEP7_PRICING
        assert TEST_ADMISSION_EVIDENCE in PROFILES_BY_FAMILY[family].form_tests


def test_form_test_stage_carries_the_admission_outcomes() -> None:
    debt = evaluate_form_tests(_table(_LADDER_ROWS, prose_before=_DEBT_PROSE))
    j1 = next(o for o in debt if o.test_id == "debt_maturity_j1_admission")
    assert j1.passed and j1.points == 0.0
    cc = evaluate_form_tests(
        _table(_PERIOD_ROWS, caption_stack=("Commitments and Contingencies",))
    )
    joint = next(o for o in cc if o.test_id == "commitments_joint_admission")
    assert joint.passed and joint.points == 0.0


def _residual(tier: str, detail: str) -> Classification:
    return Classification(
        family=RESIDUAL_FAMILY,
        flavor=None,
        kind=TableKind.NOTE_DETAIL,
        tier=tier,
        score=0.0,
        evidence=(Evidence("genre_refusal", detail, 0.0),),
    )


def test_assembly_seat_claims_a_genre_refused_joint_table() -> None:
    table = _table(_PERIOD_ROWS, caption_stack=("Commitments and Contingencies",))
    result = _residual("genre_refusal", "narrative table refused as prose")
    seated, scores = _seat_joint_evidence([table], [result], [{}])
    assert seated[0].family == "commitments_contingencies"
    assert seated[0].tier == "evidence"
    assert seated[0].score == ASSIGNMENT_FLOOR
    assert scores[0]["commitments_contingencies"] == ASSIGNMENT_FLOOR


def test_assembly_seat_leaves_a_full_refusal_residual() -> None:
    table = _table(_PERIOD_ROWS, caption_stack=("Commitments and Contingencies",))
    result = _residual("genre_refusal", "toc refused: contents page")
    seated, _ = _seat_joint_evidence([table], [result], [{}])
    assert seated[0].family == RESIDUAL_FAMILY


def test_assembly_seat_leaves_a_joint_failing_residual() -> None:
    rows = (("Accrued expenses", "400"), ("Other current liabilities", "50"))
    table = _table(rows, caption_stack=("Commitments and Contingencies",))
    result = _residual("residual", "no family at floor")
    seated, _ = _seat_joint_evidence([table], [result], [{}])
    assert seated[0].family == RESIDUAL_FAMILY


def _passed_outcome(family: str, test_id: str, passed: bool = True) -> FormTestOutcome:
    return FormTestOutcome(
        family,
        test_id,
        TEST_ADMISSION_EVIDENCE,
        passed,
        True,
        0,
        0.0,
        "priced read",
    )


_J1 = _passed_outcome("debt_maturity", "debt_maturity_j1_admission")
_JOINT = _passed_outcome("commitments_contingencies", "commitments_joint_admission")
_LEASE_SCORE = {
    "lease_maturity": FamilyScore("lease_maturity", 11.0, {"signature": 11.0}, ())
}


def test_competition_admits_j1_on_a_residual_geometry() -> None:
    result = compete(GeometryText(form_tests=(_J1,)), scores={})
    assert result.claims == ("debt_maturity",)
    group = result.groups[0]
    assert group.state == "admission"
    assert group.score == CLAIM_FLOOR


def test_competition_holds_j1_when_another_family_claims() -> None:
    result = compete(GeometryText(form_tests=(_J1,)), scores=dict(_LEASE_SCORE))
    assert result.claims == ("lease_maturity",)


def test_competition_admits_joint_beside_another_claim() -> None:
    result = compete(GeometryText(form_tests=(_JOINT,)), scores=dict(_LEASE_SCORE))
    assert set(result.claims) == {"lease_maturity", "commitments_contingencies"}
    joint = next(g for g in result.groups if g.family == "commitments_contingencies")
    assert joint.state == "admission"


def test_competition_skips_a_failed_admission_outcome() -> None:
    failed = _passed_outcome("debt_maturity", "debt_maturity_j1_admission", False)
    result = compete(GeometryText(form_tests=(failed,)), scores={})
    assert result.claims == ()
