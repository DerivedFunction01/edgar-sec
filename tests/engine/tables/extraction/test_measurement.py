"""Step 4 measurement protocol: records, estimators, pricings."""

import pytest

from edgar_sec.engine.tables.extraction.measurement import (
    AdjudicationRecord,
    GroupReturn,
    SealRecord,
    accession_list_hash,
    aoci_gate_sign,
    calibration_rows,
    close_status,
    false_claim_classes,
    is_true_class,
    labelled_recall,
    precision_rates,
    sweep_recall,
    top_member_rates,
    unclassified_remainder,
    verify_disjoint,
)


def rec(specimen, stratum, family, verdict, **kw):
    """One adjudication record with false-claim fields filled."""
    if verdict == "not-member" and "false_claim_true_class" not in kw:
        kw["false_claim_true_class"] = "composition"
        kw["false_claim_mechanism"] = "mixed"
    return AdjudicationRecord(specimen, stratum, family, verdict, **kw)


def test_false_claim_requires_class_and_mechanism():
    bad = AdjudicationRecord("s1", "B", "balance_sheet", "not-member")
    assert "false claim without false_claim_true_class" in bad.problems()
    good = rec("s1", "B", "balance_sheet", "not-member")
    assert good.problems() == ()
    member = rec("s2", "B", "balance_sheet", "member")
    assert member.problems() == ()
    assert not member.is_false_claim


def test_gold_true_family_must_be_classed_gold():
    wrong = rec(
        "s1",
        "D",
        "balance_sheet",
        "member",
        true_family="fair_value",
        false_claim_true_class="hierarchy",
        false_claim_mechanism="stub-mass",
    )
    assert wrong.is_false_claim
    assert "gold true family must be classed gold:<family>" in wrong.problems()
    right = rec(
        "s1",
        "D",
        "balance_sheet",
        "member",
        true_family="fair_value",
        false_claim_true_class="gold:fair_value",
        false_claim_mechanism="stub-mass",
    )
    assert right.problems() == ()


def test_true_class_vocabulary():
    assert is_true_class("gold:commitments_contingencies")
    assert is_true_class("gold:pension")
    assert is_true_class("hierarchy")
    assert is_true_class("host-shape:equity_statement")
    assert is_true_class("neighbor-shape:inventory")
    assert is_true_class("unclassified")
    assert not is_true_class("gold:not_a_family")
    assert not is_true_class("free-text-note")


def test_precision_rates_strict_and_form_present():
    records = (
        rec("a", "B", "cash_flow", "member"),
        rec("b", "B", "cash_flow", "split-group"),
        rec("c", "B", "cash_flow", "not-member"),
        rec("d", "B", "cash_flow", "member"),
    )
    strict, form = precision_rates(records)
    assert strict.value == 0.5 and strict.n == 4
    assert form.value == 0.75
    assert strict.estimator != form.estimator


def test_recall_estimators_are_distinct_and_labelled():
    sample = (
        rec("a", "D", "pension", "member"),
        rec(
            "b",
            "D",
            "cash_flow",
            "not-member",
            true_family="pension",
            false_claim_true_class="gold:pension",
            false_claim_mechanism="mixed",
        ),
        rec("c", "D", "pension", "member"),
    )
    labelled = labelled_recall(sample, "pension", "D")
    assert labelled.estimator == "recall-labelled-sample"
    assert labelled.value == pytest.approx(2 / 3)
    swept = sweep_recall(30.0, 10, 40, 400, "pension", "D")
    assert swept.estimator == "recall-sweep-estimated"
    assert swept.value == pytest.approx(30.0 / 130.0)


def test_unclassified_remainder_is_priced_per_stratum():
    records = (
        rec("a", "B", "ppe", "not-member"),
        rec(
            "b",
            "B",
            "ppe",
            "not-member",
            false_claim_true_class="unclassified",
            false_claim_mechanism="mixed",
        ),
        rec("c", "D", "ppe", "member"),
    )
    out = unclassified_remainder(records)
    assert out["B"].value == 0.5 and out["B"].n == 2
    assert out["D"].n == 0 and out["D"].value is None


def test_grouped_top_member_and_calibration():
    returns = (
        GroupReturn("a", "B", "debt_maturity", 12.0, "contested", True),
        GroupReturn("b", "B", "debt_maturity", 6.0, "contested", True),
        GroupReturn("c", "B", "lease_maturity", 11.0, "claimed", False),
    )
    records = (
        rec("a", "B", "debt_maturity", "member"),
        rec("b", "B", "debt_maturity", "not-member"),
        rec("c", "B", "lease_maturity", "member"),
    )
    tops = top_member_rates(returns, records)
    assert len(tops) == 1
    assert tops[0].family == "debt_maturity" and tops[0].value == 0.5
    bands = {(r.estimator, r.stratum): r for r in calibration_rows(returns, records)}
    assert bands[("calibration[10,15)", "B")].value == 1.0
    assert bands[("calibration[5,7.5)", "B")].value == 0.0


def test_aoci_gate_sign_both_decisions():
    repeat = aoci_gate_sign((rec("a", "D", "aoci_rollforward", "member"),))
    assert repeat.decision == "remove"
    assert repeat.true_members_killed == 1 and repeat.false_claims_killed == 0
    priced = aoci_gate_sign(
        (
            rec("a", "D", "aoci_rollforward", "member"),
            rec("b", "D", "aoci_rollforward", "not-member"),
        )
    )
    assert priced.decision == "accept" and priced.false_claims_killed == 1
    vacuous = aoci_gate_sign(())
    assert vacuous.decision == "accept" and vacuous.differing == 0


def test_false_claim_classes_keep_strata_apart():
    records = (
        rec(
            "a",
            "B",
            "balance_sheet",
            "not-member",
            false_claim_true_class="hierarchy",
            false_claim_mechanism="stub-mass",
        ),
        rec("b", "D", "balance_sheet", "not-member"),
    )
    out = false_claim_classes(records, "balance_sheet")
    assert out == {"B:hierarchy": 1, "D:composition": 1}


def test_disjointness_and_seal_discipline():
    drawn = {"a1", "a2", "a3"}
    prior = {"backbone": {"x"}, "population": {"a2"}}
    assert verify_disjoint(drawn, prior) == {"backbone": 0, "population": 1}
    assert accession_list_hash(drawn) == accession_list_hash({"a3", "a1", "a2"})
    seal = SealRecord("B", "h", "2026-11-14T08:00:00Z", "cap 60/family")
    spent = seal.open("2026-11-14T09:00:00Z")
    assert spent.spent
    with pytest.raises(ValueError):
        spent.open("2026-11-14T10:00:00Z")
    with pytest.raises(ValueError):
        seal.open("2026-11-14T07:00:00Z")


def test_close_status_names_half_close():
    form_of = {"B": "10-K", "D": "10-Q"}
    rates = precision_rates((rec("a", "B", "ppe", "member"),))
    assert close_status(rates, "ppe", form_of) == "half-close-10-K-only"
    both = rates + precision_rates((rec("b", "D", "ppe", "member"),))
    assert close_status(both, "ppe", form_of) == "closed-both-forms"
    assert close_status(rates, "inventory", form_of) == "open"
