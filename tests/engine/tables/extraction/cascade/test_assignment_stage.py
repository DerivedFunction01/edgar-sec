"""Assignment stage: preservation of pass-removed claims."""

from __future__ import annotations

from edgar_sec.engine.tables.extraction.cascade.assignment_stage import (
    apply_assignment_stage,
    preserve_assignment_claims,
)
from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_scoring import (
    ClaimEvidence,
    ClaimGroup,
    CompetitionResult,
    FamilyScore,
)
from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_text import (
    GeometryText,
)


def _score(family, total=11.0, evidence=()):
    return FamilyScore(family, total, {"signature": total}, evidence)


def _result(*families, groups=(), scores=None):
    if scores is None:
        scores = {family: _score(family) for family in families}
    return CompetitionResult(
        claims=families, contested=(), scores=scores, groups=groups
    )


def _group(family, state="claimed", role="head"):
    return ClaimGroup(family, 11.0, state, role, {"signature": 11.0}, (), 0.0)


def test_removed_claim_reseated_with_rebuilt_group():
    geometry = GeometryText(caption="Consolidated Statements of Operations")
    veto = (ClaimEvidence("veto", "hard:test term", 0.0),)
    entering = _result(
        "income_statement",
        "cash_flow",
        scores={
            "income_statement": _score("income_statement", 9.5, veto),
            "cash_flow": _score("cash_flow"),
        },
    )
    assigned = _result("cash_flow", groups=(_group("cash_flow"),))
    assigned = CompetitionResult(
        claims=assigned.claims,
        contested=assigned.contested,
        scores=entering.scores,
        groups=assigned.groups,
    )
    (out,) = preserve_assignment_claims([geometry], [entering], [assigned])
    assert out.claims == ("cash_flow", "income_statement")
    restored = next(g for g in out.groups if g.family == "income_statement")
    assert restored.state == "claimed"
    assert restored.role == "head"
    assert restored.score == 9.5
    assert restored.channels == {"signature": 9.5}
    assert restored.veto_flags == ("hard:test term",)
    assert restored.explained_foreign == 0.0


def test_no_removal_returns_result_unchanged():
    geometry = GeometryText(stubs=("Revenues",))
    result = _result("income_statement")
    (out,) = preserve_assignment_claims([geometry], [result], [result])
    assert out is result


def test_surviving_group_is_not_duplicated():
    geometry = GeometryText(caption="Changes in Equity")
    entering = _result("equity_statement")
    kept = _group("equity_statement")
    assigned = CompetitionResult(
        claims=(), contested=(), scores=entering.scores, groups=(kept,)
    )
    (out,) = preserve_assignment_claims([geometry], [entering], [assigned])
    assert out.claims == ("equity_statement",)
    assert out.groups == (kept,)


def test_scoreless_family_reseats_without_group():
    geometry = GeometryText(caption="Notes")
    entering = _result("lease_maturity")
    assigned = CompetitionResult(claims=(), contested=(), scores={}, groups=())
    (out,) = preserve_assignment_claims([geometry], [entering], [assigned])
    assert out.claims == ("lease_maturity",)
    assert out.groups == ()


def test_multiple_removals_append_in_sorted_order():
    geometry = GeometryText(caption="Statements")
    entering = _result("lease_maturity", "income_statement", "cash_flow")
    assigned = _result("cash_flow", groups=(_group("cash_flow"),))
    assigned = CompetitionResult(
        claims=assigned.claims,
        contested=assigned.contested,
        scores=entering.scores,
        groups=assigned.groups,
    )
    (out,) = preserve_assignment_claims([geometry], [entering], [assigned])
    assert out.claims == ("cash_flow", "income_statement", "lease_maturity")


def test_group_role_follows_geometry_shape():
    entering = _result("income_statement")
    assigned = CompetitionResult(
        claims=(), contested=(), scores=entering.scores, groups=()
    )
    fragment = GeometryText(stubs=("Revenues",))
    (out,) = preserve_assignment_claims([fragment], [entering], [assigned])
    assert out.groups[0].role == "continuation"
    standalone = GeometryText(stubs=tuple(f"Stub {i}" for i in range(9)))
    (out,) = preserve_assignment_claims([standalone], [entering], [assigned])
    assert out.groups[0].role == "standalone"


def _channeled_score(family, channels):
    return FamilyScore(family, sum(channels.values()), channels, ())


def _removed(family, channels):
    geometry = GeometryText(caption="Statements")
    entering = _result(family, scores={family: _channeled_score(family, channels)})
    assigned = CompetitionResult(
        claims=(), contested=(), scores=entering.scores, groups=()
    )
    (out,) = preserve_assignment_claims([geometry], [entering], [assigned])
    return out


def test_context_only_income_statement_claim_stays_removed():
    out = _removed("income_statement", {"context": 10.4566})
    assert out.claims == ()
    assert out.groups == ()


def test_mixed_channel_income_statement_claim_stays_removed():
    out = _removed("income_statement", {"context": 2.9724, "signature": 0.7362})
    assert out.claims == ()
    assert out.groups == ()


def test_own_evidence_income_statement_claim_reseated():
    out = _removed("income_statement", {"signature": 11.0})
    assert out.claims == ("income_statement",)
    assert out.groups[0].channels == {"signature": 11.0}


def test_zero_context_income_statement_claim_reseated():
    out = _removed("income_statement", {"context": 0.0, "signature": 9.0})
    assert out.claims == ("income_statement",)


def test_context_carried_other_family_claim_reseated():
    out = _removed("equity_statement", {"context": 8.2888})
    assert out.claims == ("equity_statement",)
    assert out.groups[0].family == "equity_statement"


def test_refusal_leaves_sibling_reseat_intact():
    geometry = GeometryText(caption="Statements")
    entering = _result(
        "income_statement",
        "cash_flow",
        scores={
            "income_statement": _channeled_score(
                "income_statement", {"context": 8.2888}
            ),
            "cash_flow": _score("cash_flow"),
        },
    )
    assigned = _result("cash_flow", groups=(_group("cash_flow"),))
    assigned = CompetitionResult(
        claims=assigned.claims,
        contested=assigned.contested,
        scores=entering.scores,
        groups=assigned.groups,
    )
    (out,) = preserve_assignment_claims([geometry], [entering], [assigned])
    assert out.claims == ("cash_flow",)
    assert [g.family for g in out.groups] == ["cash_flow"]


def test_stage_restores_a_real_pass_removal():
    geometry = GeometryText(stubs=("Asset retirement obligations",))
    groups = (
        _group("aro_rollforward"),
        _group("warranty"),
    )
    entering = _result("aro_rollforward", "warranty", groups=groups)
    (out,) = apply_assignment_stage([geometry], [entering])
    assert "aro_rollforward" in out.claims
    assert "warranty" in out.claims
