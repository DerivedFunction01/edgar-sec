"""Spanning veto pass: the priced CF-1, CF-2, CF-3, BS-1 legs."""

from __future__ import annotations

from edgar_sec.engine.tables.extraction.cascade.competition import (
    DOMINANCE_RATIO,
)
from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_scoring import (
    ClaimGroup,
    CompetitionResult,
    FamilyScore,
)
from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_text import (
    GeometryText,
)
from edgar_sec.engine.tables.extraction.core.subjects.profile_constants import (
    TEST_SIGNATURE_ABSENCE,
)
from edgar_sec.engine.tables.extraction.form_specs.form_test_types import (
    FormTestOutcome,
)
from edgar_sec.engine.tables.extraction.vetoes.spanning_veto_evidence import (
    apply_spanning_vetoes,
)
from edgar_sec.engine.tables.extraction.vetoes.spanning_veto_specs import (
    BS_FILING_RELATIVE_FLOOR,
    CF_DOMINANCE_RATIO,
)


def _score(family, total=11.0):
    return FamilyScore(family, total, {"stub": total}, ())


def _result(claims, totals):
    scores = {family: _score(family, total) for family, total in totals.items()}
    return CompetitionResult(
        claims=tuple(claims),
        contested=tuple(claims),
        scores=scores,
        groups=tuple(
            ClaimGroup(f, totals[f], "claimed", "head", {"stub": totals[f]}, (), 0.0)
            for f in claims
        ),
    )


def _gate_details(result, family="cash_flow"):
    return [
        item.detail for item in result.scores[family].evidence if item.channel == "gate"
    ]


def test_ratio_constant_restates_production_dominance():
    assert CF_DOMINANCE_RATIO == DOMINANCE_RATIO


def test_non_dominant_cash_flow_claim_removed():
    geo = GeometryText()
    results = apply_spanning_vetoes(
        [geo],
        [
            _result(
                ("cash_flow", "income_statement"),
                {"cash_flow": 8.45, "income_statement": 8.45},
            )
        ],
    )
    assert "cash_flow" not in results[0].claims
    assert "cash_flow" not in results[0].contested
    assert results[0].scores["cash_flow"].total == 8.45
    assert _gate_details(results[0]) == ["spanning veto: dominance"]
    assert [group.family for group in results[0].groups] == ["income_statement"]


def test_dominant_cash_flow_claim_kept():
    geo = GeometryText()
    results = apply_spanning_vetoes(
        [geo],
        [
            _result(
                ("cash_flow", "income_statement"),
                {"cash_flow": 13.0, "income_statement": 8.45},
            )
        ],
    )
    assert "cash_flow" in results[0].claims
    assert _gate_details(results[0]) == []


def test_exact_ratio_boundary_kept():
    geo = GeometryText()
    results = apply_spanning_vetoes(
        [geo],
        [
            _result(
                ("cash_flow", "income_statement"),
                {"cash_flow": 12.5, "income_statement": 10.0},
            )
        ],
    )
    assert "cash_flow" in results[0].claims


def test_claimed_rival_dominates():
    geo = GeometryText()
    results = apply_spanning_vetoes(
        [geo],
        [_result(("cash_flow", "ppe"), {"cash_flow": 20.0, "ppe": 30.0})],
    )
    assert "cash_flow" not in results[0].claims
    assert "ppe" in results[0].claims


def test_unclaimed_rival_does_not_dominate():
    geo = GeometryText()
    results = apply_spanning_vetoes(
        [geo],
        [_result(("cash_flow",), {"cash_flow": 20.0, "ppe": 30.0})],
    )
    assert "cash_flow" in results[0].claims
    assert _gate_details(results[0]) == []


def test_unclaimed_cash_flow_never_fires():
    geo = GeometryText()
    results = apply_spanning_vetoes(
        [geo],
        [_result(("ppe",), {"cash_flow": 3.0, "ppe": 30.0})],
    )
    assert "ppe" in results[0].claims
    assert _gate_details(results[0], "cash_flow") == []


def _absence_outcome(passed, evaluable=True, family="cash_flow"):
    return FormTestOutcome(
        family,
        "cash_flow_signature_absence",
        TEST_SIGNATURE_ABSENCE,
        passed,
        evaluable,
        0,
        1.0,
        "stub",
    )


def _dominant_cf():
    return _result(("cash_flow",), {"cash_flow": 13.0, "income_statement": 8.45})


def test_signature_absence_failed_claim_removed():
    geo = GeometryText(form_tests=(_absence_outcome(False),))
    results = apply_spanning_vetoes([geo], [_dominant_cf()])
    assert "cash_flow" not in results[0].claims
    assert _gate_details(results[0]) == ["spanning veto: signature"]


def test_signature_unevaluable_claim_removed():
    geo = GeometryText(form_tests=(_absence_outcome(False, evaluable=False),))
    results = apply_spanning_vetoes([geo], [_dominant_cf()])
    assert "cash_flow" not in results[0].claims
    assert _gate_details(results[0]) == ["spanning veto: signature"]


def test_signature_passed_claim_kept():
    geo = GeometryText(form_tests=(_absence_outcome(True),))
    results = apply_spanning_vetoes([geo], [_dominant_cf()])
    assert "cash_flow" in results[0].claims
    assert _gate_details(results[0]) == []


def test_signature_outcome_absent_claim_kept():
    geo = GeometryText(form_tests=())
    results = apply_spanning_vetoes([geo], [_dominant_cf()])
    assert "cash_flow" in results[0].claims


def test_signature_leg_scoped_to_cash_flow():
    geo = GeometryText(form_tests=(_absence_outcome(False, family="balance_sheet"),))
    results = apply_spanning_vetoes(
        [geo],
        [_result(("balance_sheet",), {"balance_sheet": 30.0, "ppe": 20.0})],
    )
    assert "balance_sheet" in results[0].claims


def test_signature_cluster_member_pass_keeps_claim():
    frag = GeometryText(form_tests=(_absence_outcome(False),))
    body = GeometryText(form_tests=(_absence_outcome(True),))
    results = apply_spanning_vetoes(
        [frag, body],
        [_dominant_cf(), _result((), {})],
    )
    assert "cash_flow" in results[0].claims
    assert _gate_details(results[0]) == []


def test_signature_cluster_without_pass_removed():
    frag = GeometryText(form_tests=(_absence_outcome(False),))
    other = GeometryText(form_tests=())
    results = apply_spanning_vetoes(
        [frag, other],
        [_dominant_cf(), _result((), {})],
    )
    assert "cash_flow" not in results[0].claims
    assert _gate_details(results[0]) == ["spanning veto: signature"]


def test_both_cf_legs_report_together():
    geo = GeometryText(form_tests=(_absence_outcome(False),))
    results = apply_spanning_vetoes(
        [geo],
        [
            _result(
                ("cash_flow", "income_statement"),
                {"cash_flow": 8.45, "income_statement": 8.45},
            )
        ],
    )
    assert "cash_flow" not in results[0].claims
    assert _gate_details(results[0]) == ["spanning veto: dominance, signature"]


def test_filing_relative_floor_is_the_priced_value():
    assert BS_FILING_RELATIVE_FLOOR == 0.4


def test_filing_relative_below_floor_removed():
    geos = [GeometryText(), GeometryText()]
    results = apply_spanning_vetoes(
        geos,
        [
            _result(("balance_sheet",), {"balance_sheet": 30.0}),
            _result(("balance_sheet",), {"balance_sheet": 8.0}),
        ],
    )
    assert "balance_sheet" in results[0].claims
    assert "balance_sheet" not in results[1].claims
    assert _gate_details(results[1], "balance_sheet") == [
        "spanning veto: filing-relative"
    ]


def test_filing_relative_below_floor_closing_total_kept():
    geos = [
        GeometryText(),
        GeometryText(stubs=("Total liabilities and stockholders' equity",)),
    ]
    results = apply_spanning_vetoes(
        geos,
        [
            _result(("balance_sheet",), {"balance_sheet": 60.0}),
            _result(("balance_sheet",), {"balance_sheet": 16.0}),
        ],
    )
    assert "balance_sheet" in results[1].claims


def test_filing_relative_at_floor_kept():
    geos = [GeometryText(), GeometryText()]
    results = apply_spanning_vetoes(
        geos,
        [
            _result(("balance_sheet",), {"balance_sheet": 30.0}),
            _result(("balance_sheet",), {"balance_sheet": 12.0}),
        ],
    )
    assert "balance_sheet" in results[1].claims


def test_filing_relative_single_claim_kept():
    geo = GeometryText()
    results = apply_spanning_vetoes(
        [geo],
        [_result(("balance_sheet",), {"balance_sheet": 8.0})],
    )
    assert "balance_sheet" in results[0].claims


def test_filing_relative_ignores_unclaimed_scores():
    geos = [GeometryText(), GeometryText()]
    results = apply_spanning_vetoes(
        geos,
        [
            _result(("ppe",), {"balance_sheet": 90.0, "ppe": 30.0}),
            _result(("balance_sheet",), {"balance_sheet": 8.0}),
        ],
    )
    assert "balance_sheet" in results[1].claims


def test_signature_fragment_title_identity_claim_kept():
    geo = GeometryText(
        lead_title="Supplemental Cash Flow Information",
        form_tests=(_absence_outcome(False),),
    )
    results = apply_spanning_vetoes([geo], [_dominant_cf()])
    assert "cash_flow" in results[0].claims
    assert _gate_details(results[0]) == []


def test_signature_recon_block_identity_claim_kept():
    geo = GeometryText(
        stubs=("Total cash and cash equivalents",),
        form_tests=(_absence_outcome(False),),
    )
    results = apply_spanning_vetoes([geo], [_dominant_cf()])
    assert "cash_flow" in results[0].claims
    assert _gate_details(results[0]) == []


def test_signature_fragment_identity_dominance_still_removes():
    geo = GeometryText(
        lead_title="Supplemental Cash Flow Information",
        form_tests=(_absence_outcome(False),),
    )
    results = apply_spanning_vetoes(
        [geo],
        [
            _result(
                ("cash_flow", "income_statement"),
                {"cash_flow": 8.45, "income_statement": 8.45},
            )
        ],
    )
    assert "cash_flow" not in results[0].claims
    assert _gate_details(results[0]) == ["spanning veto: dominance, signature"]


def _cf_result_with_channels(channels, total):
    score = FamilyScore("cash_flow", total, channels, ())
    return CompetitionResult(
        claims=("cash_flow",),
        contested=("cash_flow",),
        scores={"cash_flow": score},
        groups=(ClaimGroup("cash_flow", total, "claimed", "head", channels, (), 0.0),),
    )


def test_context_carried_claim_removed():
    # The priced specimen shape: the whole standing mass is
    # inherited notehead context (share 6.2 / 5.7 > 0.5).
    result = _cf_result_with_channels(
        {"notehead": 6.2, "form_test": 1.0, "veto": -1.5}, 5.7
    )
    results = apply_spanning_vetoes([GeometryText()], [result])
    assert "cash_flow" not in results[0].claims
    assert _gate_details(results[0]) == ["spanning veto: context"]


def test_context_share_at_ceiling_kept():
    result = _cf_result_with_channels({"notehead": 5.0, "stub": 5.0}, 10.0)
    results = apply_spanning_vetoes([GeometryText()], [result])
    assert "cash_flow" in results[0].claims
    assert _gate_details(results[0]) == []


def test_context_share_fragment_shape_kept():
    # The waiver pair's shape: a fragment whose own channels
    # carry the score (share 2.06 / 12.63) stands.
    result = _cf_result_with_channels(
        {"notehead": 2.06, "leadin": 12.06, "lead_title": 2.41}, 12.63
    )
    results = apply_spanning_vetoes([GeometryText()], [result])
    assert "cash_flow" in results[0].claims
    assert _gate_details(results[0]) == []
