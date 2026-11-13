"""Verdict scoring: original, full-report, and strata accountings."""

from __future__ import annotations

from tools.table_extraction_corpus.verdict import (
    error_classes,
    placement_category,
    score_rows,
    stratum_of,
)


def _row(
    gold,
    pred,
    *,
    stratum="audited",
    mechanism="winner",
    group_family=None,
    group_role=None,
    group_tags=(),
    section_member=False,
):
    return {
        "gold": gold,
        "pred": pred,
        "stratum": stratum,
        "mechanism": mechanism,
        "group_family": group_family if group_family is not None else pred,
        "group_role": group_role,
        "group_tags": tuple(group_tags),
        "section_member": section_member,
    }


def test_stratum_of_reads_the_label_stamps():
    assert stratum_of(None) == "unlabelled"
    assert stratum_of({"provenance": "signature", "audited": True}) == "signature"
    assert stratum_of({"provenance": "aligned", "audited": True}) == "audited"
    assert (
        stratum_of({"provenance": "aligned_negative", "audited": False})
        == "aligned_negative"
    )
    assert stratum_of({"provenance": None, "audited": False}) == "unlabelled"
    assert stratum_of({"provenance": None, "audited": True}) == "audited"


def test_error_classes_match_the_verdict_decomposition():
    assert error_classes(_row("cash_flow", "cash_flow")) == (None, None)
    assert error_classes(_row("cash_flow", "other")) == ("fn_to_residual", None)
    assert error_classes(_row("cash_flow", "balance_sheet")) == (
        "fn_to_rival",
        "fp_rival",
    )
    assert error_classes(_row("other", "cash_flow")) == (None, "fp_residual_gold")
    assert error_classes(_row(None, "cash_flow")) == (None, "fp_unlabelled")
    assert error_classes(_row("equity_statement", "aoci")) == (
        "fn_to_related",
        "fp_containment_consistent",
    )
    assert error_classes(_row("aoci", "equity_statement")) == (
        "fn_to_related",
        "fp_parent_over_subset",
    )
    dual = _row(
        "balance_sheet", "fair_value", group_tags=("fair_value", "balance_sheet")
    )
    assert error_classes(dual) == ("fn_to_rival", "fp_dual_consistent")


def test_placement_categories_cover_the_positions():
    assert placement_category(_row("cash_flow", "cash_flow", group_role="main")) == (
        "exact_main"
    )
    assert (
        placement_category(_row("cash_flow", "cash_flow", group_role="variant"))
        == "exact_variant"
    )
    assert (
        placement_category(
            _row(
                "cash_flow",
                "cash_flow",
                group_role="variant",
                group_tags=("cash_flow", "second_set"),
            )
        )
        == "exact_second_set"
    )
    assert (
        placement_category(
            _row(
                "aoci",
                "aoci",
                mechanism="section",
                group_family="equity_statement",
                section_member=True,
            )
        )
        == "exact_section"
    )
    assert placement_category(_row("other", "other")) == "residual"
    assert placement_category(_row("other", "segment_reporting")) == ("admitted_family")
    assert placement_category(_row(None, "subsequent_events")) == "admitted_family"
    assert placement_category(_row(None, "other")) == "unlabelled_residual"
    assert placement_category(_row(None, "cash_flow")) is None
    assert placement_category(_row("other", "cash_flow")) is None
    assert (
        placement_category(
            _row(
                "equity_statement",
                "aoci",
                mechanism="section",
                group_family="equity_statement",
                section_member=True,
            )
        )
        == "section_of_gold"
    )
    assert placement_category(_row("equity_statement", "aoci")) == "contained_subset"
    assert placement_category(_row("aoci", "equity_statement")) == "contained_parent"
    assert (
        placement_category(
            _row(
                "balance_sheet",
                "fair_value",
                group_tags=("fair_value", "balance_sheet"),
            )
        )
        == "dual_service"
    )
    assert placement_category(_row("cash_flow", "balance_sheet")) is None


def test_score_rows_reports_all_three_accountings():
    rows = [
        _row("cash_flow", "cash_flow", group_role="main"),
        _row("cash_flow", "cash_flow", group_role="variant"),
        _row("cash_flow", "other", stratum="aligned_negative"),
        _row("other", "segment_reporting", stratum="aligned_negative"),
        _row("other", "other", stratum="aligned_negative"),
        _row(None, "other", stratum="unlabelled"),
        _row(None, "cash_flow", stratum="unlabelled"),
    ]
    groups = [
        {
            "family": "cash_flow",
            "role": "main",
            "tags": ("cash_flow",),
            "head_gold": "cash_flow",
            "member_golds": ["cash_flow", "cash_flow"],
        },
        {
            "family": "segment_reporting",
            "role": "main",
            "tags": ("segment_reporting",),
            "head_gold": "other",
            "member_golds": ["other"],
        },
    ]
    out = score_rows(rows, groups)
    cash = out["families"]["cash_flow"]
    assert (cash["support"], cash["predicted"], cash["correct"]) == (3, 3, 2)
    assert cash["mains"] == 1 and cash["mains_head_correct"] == 1
    assert cash["false_negatives"] == {"fn_to_residual": 1, "assigned:other": 1}
    assert out["decomposition"] == {"fp_residual_gold": 1, "fp_unlabelled": 1}
    assert out["total_correct"] == 3 and out["named_correct"] == 2
    assert out["verdicts"]["cash_flow"]["pass"] is False
    placement = out["placement"]
    assert placement["by_category"] == {
        "exact_main": 1,
        "exact_variant": 1,
        "admitted_family": 1,
        "residual": 1,
        "unlabelled_residual": 1,
    }
    assert placement["placed"] == 4 and placement["placed_labelled"] == 4
    assert placement["placed_rate_labelled"] == 0.8
    seg = placement["families"]["segment_reporting"]
    assert seg["support"] == 0 and seg["placed_from_pred"] == 1
    assert seg["placement_precision"] == 1.0
    audited = out["strata"]["audited"]
    assert audited["scored"] == 2 and audited["total_correct"] == 2
    aligned = out["strata"]["aligned_negative"]
    assert aligned["scored"] == 3 and aligned["named_correct"] == 0
    assert out["strata"]["unlabelled"]["scored"] == 2
