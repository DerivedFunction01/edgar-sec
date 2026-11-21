"""Credit-losses seat: registry data, the priced conjunction, pins."""

from __future__ import annotations

from edgar_sec.engine.tables.ascii_html.model import (
    ResolvedGrid,
    TableGeometry,
    TableRenderResult,
)
from edgar_sec.engine.tables.extraction.core.context import TableContext
from edgar_sec.engine.tables.extraction.evidence.credit_losses_evidence import (
    CreditLossesLegs,
    CreditLossesText,
    evaluate_form_test_credit_losses,
    legs_for,
)
from edgar_sec.engine.tables.extraction.specs.credit_losses_specs import (
    CREDIT_LOSSES_EVIDENCE_SPECS,
    CREDIT_LOSSES_EVIDENCE_SPECS_BY_TEST_ID,
)
from edgar_sec.engine.tables.extraction.form_specs.form_test_specs import (
    FORM_TEST_SPECS,
)
from edgar_sec.engine.tables.extraction.form_tests.form_tests import evaluate_form_tests
from edgar_sec.engine.tables.extraction.core.profiles import (
    PROV_S5_SEAT_PRICING,
    TEST_CREDIT_LOSSES_EVIDENCE,
    TEST_CREDIT_SEPARATOR,
    profile_for,
)
from edgar_sec.engine.tables.extraction.core.typed_rows import structure_table

SPEC = CREDIT_LOSSES_EVIDENCE_SPECS["credit_losses_rollforward"]


def _table(
    rows: tuple[tuple[str, ...], ...],
    caption: tuple[str, ...] = (),
    prose_before: str = "",
):
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
        geometry=geometry, caption_stack=caption, prose_before=prose_before
    )
    return structure_table(context)


def _legs(table) -> CreditLossesLegs:
    return legs_for(CreditLossesText.from_table(table), SPEC)


def test_seat_is_declared_as_form_test_data():
    entry = next(
        s for s in FORM_TEST_SPECS if s.test_id == "credit_losses_rollforward_evidence"
    )
    assert entry.family == "credit_losses_rollforward"
    assert entry.kind == TEST_CREDIT_LOSSES_EVIDENCE
    assert entry.points == 3.0
    assert entry.provenance == PROV_S5_SEAT_PRICING
    assert SPEC.provenance == PROV_S5_SEAT_PRICING
    assert CREDIT_LOSSES_EVIDENCE_SPECS_BY_TEST_ID[SPEC.test_id] is SPEC
    profile = profile_for("credit_losses_rollforward")
    assert profile is not None
    assert profile.form_tests == (TEST_CREDIT_LOSSES_EVIDENCE, TEST_CREDIT_SEPARATOR)
    assert profile.support is not None
    assert profile.support.annual_precision is None
    assert profile.support.quarterly_precision is None


def test_filed_shape_walk_claims():
    table = _table(
        (
            ("Balance at beginning of year", "100"),
            ("Provision for credit losses", "10"),
            ("Charge-offs", "(5)"),
            ("Recoveries", "2"),
            ("Balance at end of year", "107"),
        ),
        caption=("Allowance for Credit Losses",),
    )
    legs = _legs(table)
    assert legs.r1 and legs.bookends_arm3
    assert legs.movement and legs.claim
    assert evaluate_form_test_credit_losses(table, _form_spec()).admitted


def test_veto_refuses_carrier_only_da_claim():
    # Specimen 0001753926-26-000600:27: unnamed-subject walk, the
    # subject carried by prose, the full DA phrase in prose.
    table = _table(
        (
            ("Balance at beginning of the year", ""),
            ("Allowance increase (decrease)", ""),
            ("Write offs, net of recoveries", ""),
            ("Balance at end of the year", ""),
        ),
        prose_before=(
            "The allowance for loan losses and the allowance for "
            "doubtful accounts are described below."
        ),
    )
    legs = _legs(table)
    assert legs.subject and legs.carrier and not legs.r1
    assert legs.vetoed and not legs.claim
    assert not evaluate_form_test_credit_losses(table, _form_spec()).admitted


def test_carrier_claim_stands_without_the_da_phrase():
    # Specimen 0001213900-23-093999:39 carries "doubtful" only —
    # no full DA phrase, so the veto does not fire (a priced FP).
    table = _table(
        (
            ("Balance at beginning of the year", ""),
            ("Allowance increase (decrease)", ""),
            ("Write offs, net of recoveries", ""),
            ("Balance at end of the year", ""),
        ),
        prose_before=(
            "Management reviews doubtful receivables and the "
            "allowance for loan losses quarterly."
        ),
    )
    legs = _legs(table)
    assert legs.carrier and not legs.vetoed and legs.claim


def test_drawn_r1_subject_stands_with_da_phrase_in_prose():
    # TRUEs 0000950123-10-028592:13 and 0001564590-20-050757:83:
    # a drawn R1 subject is not vetoed by an incidental DA phrase.
    table = _table(
        (
            ("Balance at beginning of year", ""),
            ("Provision", ""),
            ("Balance at end of year", ""),
        ),
        caption=("Allowance for Loan Losses",),
        prose_before="The allowance for doubtful accounts was unchanged.",
    )
    legs = _legs(table)
    assert legs.r1 and not legs.vetoed and legs.claim


def test_credit_loss_expense_alone_is_not_movement():
    # D5 non-goal 0001628280-22-019174:29: "credit loss expense"
    # as sole movement evidence fails the movement leg.
    table = _table(
        (
            ("Balance, beginning of period", "1"),
            ("Credit loss expense", "5"),
            ("Balance, end of period", "6"),
        ),
        caption=("Allowance for Credit Losses",),
    )
    legs = _legs(table)
    assert legs.subject and legs.bookends_arm3
    assert not legs.movement and not legs.claim


def test_asof_pair_bookends_claim():
    table = _table(
        (
            ("Allowance for credit losses", ""),
            ("Balance as of December 31, 2023", "100"),
            ("Provision for credit losses", "10"),
            ("Balance as of December 31, 2024", "110"),
        )
    )
    legs = _legs(table)
    assert legs.bookends_baseline and legs.bookends_arm3 and legs.claim


def test_dated_anchor_bookends_claim():
    table = _table(
        (
            ("Allowance for credit losses, December 31, 2023", "100"),
            ("Provision for credit losses", "10"),
            ("Allowance for credit losses, December 31, 2024", "110"),
        )
    )
    legs = _legs(table)
    assert legs.bookends_arm3 and legs.claim


def test_subject_and_bookends_without_movement_fails():
    table = _table(
        (
            ("Balance at beginning of year", "100"),
            ("Balance at end of year", "107"),
        ),
        caption=("Allowance for Credit Losses",),
    )
    legs = _legs(table)
    assert legs.subject and legs.bookends_arm3
    assert not legs.movement and not legs.claim


def test_acl_token_subject_claims():
    table = _table(
        (
            ("ACL balance, December 31, 2022", "100"),
            ("Provision", "10"),
            ("ACL balance, December 31, 2023", "110"),
        )
    )
    legs = _legs(table)
    assert legs.acltok and not legs.r1 and legs.claim


def test_fragmented_carrier_phrase_subject_claims():
    table = _table(
        (
            ("Allowance for credit", "losses"),
            ("Balance at beginning of year", "100"),
            ("Provision", "10"),
            ("Balance at end of year", "107"),
        )
    )
    legs = _legs(table)
    assert legs.carrier and not legs.r1 and legs.claim


def test_adapter_outcome_equals_legs_claim():
    tables = (
        _table(
            (
                ("Balance at beginning of year", "100"),
                ("Provision for credit losses", "10"),
                ("Balance at end of year", "107"),
            ),
            caption=("Allowance for Credit Losses",),
        ),
        _table(
            (
                ("Balance at beginning of year", "100"),
                ("Balance at end of year", "107"),
            ),
            caption=("Allowance for Credit Losses",),
        ),
    )
    for table in tables:
        outcome = next(
            o for o in evaluate_form_tests(table) if o.test_id == SPEC.test_id
        )
        assert outcome.passed == _legs(table).claim


def _form_spec():
    return next(s for s in FORM_TEST_SPECS if s.test_id == SPEC.test_id)


def test_hyphenated_bookends_claim():
    # Specimen 0000059558-26-000016:118: "beginning-of-year /
    # end-of-year" bookends in the filer's hyphenated dialect.
    table = _table(
        (
            ("Balance as of beginning-of-year", "100"),
            ("Provision for credit losses", "10"),
            ("Balance as of end-of-year", "110"),
        ),
        caption=("Allowance for Credit Losses",),
    )
    legs = _legs(table)
    assert legs.bookends_arm3 and legs.claim
    assert evaluate_form_test_credit_losses(table, _form_spec()).admitted


def test_dated_stub_bookends_claim():
    # Specimen 0000842517-15-000076:18: the bookends are bare
    # dated stubs; the subject sits in the caption.
    table = _table(
        (
            ("January 1, 2015", "100"),
            ("Provision for credit losses", "10"),
            ("Charge-offs", "(5)"),
            ("March 31, 2015", "105"),
        ),
        caption=("Allowance for Credit Losses",),
    )
    legs = _legs(table)
    assert not legs.bookends_arm3
    assert legs.stub_pair and legs.claim
    result = evaluate_form_test_credit_losses(table, _form_spec())
    assert result.admitted
    assert "dated-stub bookends" in result.detail


def test_alll_token_subject_claims_on_arm3_bookends():
    # Specimen 0001277902 (via the token arm): the subject is
    # carried only by the ALLL stub token.
    table = _table(
        (
            ("Total ALLL", ""),
            ("Balance at beginning of year", "100"),
            ("Provision", "10"),
            ("Balance at end of year", "110"),
        )
    )
    legs = _legs(table)
    assert not legs.subject
    assert legs.token_subject and legs.bookends_arm3 and legs.claim
    result = evaluate_form_test_credit_losses(table, _form_spec())
    assert result.admitted
    assert "token subject + arm-3 bookends" in result.detail


def test_alll_token_subject_claims_on_transposed_bookends():
    # Specimen 0001628280-26-010546:68: the walk is transposed;
    # the bookends are the dated header columns.
    table = _table(
        (
            ("Total ALLL", "December 31, 2022", "December 31, 2023"),
            ("Provision", "10", "12"),
            ("Charge-offs", "(5)", "(4)"),
        )
    )
    legs = _legs(table)
    assert not legs.bookends_arm3
    assert legs.token_subject and legs.transposed and legs.claim
    result = evaluate_form_test_credit_losses(table, _form_spec())
    assert result.admitted
    assert "token subject + transposed bookends" in result.detail


def test_alll_token_without_bookends_or_movement_fails():
    table = _table(
        (
            ("Total ALLL", "100"),
            ("Balance", "110"),
        )
    )
    legs = _legs(table)
    assert legs.token_subject
    assert not legs.claim
    assert not evaluate_form_test_credit_losses(table, _form_spec()).admitted
