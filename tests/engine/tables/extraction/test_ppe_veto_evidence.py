"""PPE veto pass: the four priced legs over final claims."""

from __future__ import annotations

from edgar_sec.engine.tables.extraction.competition import GeometryText
from edgar_sec.engine.tables.extraction.geometry_scoring import (
    ClaimGroup,
    CompetitionResult,
    FamilyScore,
)
from edgar_sec.engine.tables.extraction.ppe_veto_evidence import apply_ppe_vetoes
from edgar_sec.engine.tables.extraction.ppe_veto_specs import STRONG_STUB_KEYS


def _score(family, total=11.0, channels=None):
    return FamilyScore(family, total, channels or {"stub": total}, ())


def _result(families, totals=None, channels=None, groups=()):
    totals = totals or {}
    channels = channels or {}
    scores = {
        family: _score(
            family, totals.get(family, 11.0), channels.get(family)
        )
        for family in families
    }
    return CompetitionResult(
        claims=tuple(families),
        contested=tuple(families),
        scores=scores,
        groups=groups,
    )


def _unclaimed(score):
    return CompetitionResult(claims=(), contested=(), scores={"ppe": score})


def _gate_details(result, family="ppe"):
    return [
        item.detail
        for item in result.scores[family].evidence
        if item.channel == "gate"
    ]


def test_specs_carry_the_arbitrated_strong_sets():
    assert len(STRONG_STUB_KEYS) == 11
    assert sum(len(keys) for keys in STRONG_STUB_KEYS.values()) == 22
    assert "total assets" in STRONG_STUB_KEYS["balance_sheet"]
    assert "ppe" not in STRONG_STUB_KEYS


def test_host_claim_removes_ppe_on_two_shared_keys():
    geo = GeometryText(stubs=("Total Assets", "Total Liabilities", "Land"))
    groups = (
        ClaimGroup("ppe", 11.0, "claimed", "primary", {"stub": 11.0}, (), 0.0),
        ClaimGroup(
            "balance_sheet", 5.0, "claimed", "primary", {"stub": 5.0}, (), 0.0
        ),
    )
    results = apply_ppe_vetoes(
        [geo],
        [
            _result(
                ("ppe", "balance_sheet"),
                totals={"balance_sheet": 5.0},
                groups=groups,
            )
        ],
    )
    assert "ppe" not in results[0].claims
    assert "ppe" not in results[0].contested
    assert "balance_sheet" in results[0].claims
    assert results[0].scores["ppe"].total == 11.0
    assert _gate_details(results[0]) == ["ppe veto: H2claim"]
    assert [group.family for group in results[0].groups] == ["balance_sheet"]


def test_host_claim_needs_two_shared_keys():
    geo = GeometryText(stubs=("Total Assets", "Land"))
    results = apply_ppe_vetoes(
        [geo],
        [_result(("ppe", "balance_sheet"), totals={"balance_sheet": 5.0})],
    )
    assert "ppe" in results[0].claims


def test_host_claim_needs_the_host_claiming():
    geo = GeometryText(stubs=("Total Assets", "Total Liabilities"))
    results = apply_ppe_vetoes([geo], [_result(("ppe",))])
    assert "ppe" in results[0].claims


def test_dominance_removes_on_a_tie():
    geo = GeometryText()
    results = apply_ppe_vetoes(
        [geo], [_result(("ppe", "inventory"), totals={"inventory": 11.0})]
    )
    assert "ppe" not in results[0].claims
    assert _gate_details(results[0]) == ["ppe veto: LBdomF"]


def test_dominance_keeps_below_the_tie():
    geo = GeometryText()
    results = apply_ppe_vetoes(
        [geo], [_result(("ppe", "inventory"), totals={"inventory": 10.5})]
    )
    assert "ppe" in results[0].claims


def test_lead_balance_removes_on_balanced_prose():
    geo = GeometryText()
    results = apply_ppe_vetoes(
        [geo],
        [
            _result(
                ("ppe",),
                totals={"ppe": 8.0},
                channels={"ppe": {"leadin": 4.0, "lead_title": 4.0}},
            )
        ],
    )
    assert "ppe" not in results[0].claims
    assert _gate_details(results[0]) == ["ppe veto: L6bal0.4"]


def test_lead_balance_keeps_unbalanced_prose():
    geo = GeometryText()
    results = apply_ppe_vetoes(
        [geo],
        [
            _result(
                ("ppe",),
                totals={"ppe": 5.0},
                channels={"ppe": {"leadin": 1.0, "lead_title": 4.0}},
            )
        ],
    )
    assert "ppe" in results[0].claims


def test_lead_balance_keeps_form_test_or_stub_mass():
    geo = GeometryText()
    for channels in (
        {"leadin": 4.0, "lead_title": 4.0, "form_test": 2.0},
        {"leadin": 4.0, "lead_title": 4.0, "stub": 1.0},
    ):
        results = apply_ppe_vetoes(
            [geo],
            [_result(("ppe",), totals={"ppe": 8.0}, channels={"ppe": channels})],
        )
        assert "ppe" in results[0].claims


def test_context_carried_removes_with_cross_section_mate():
    claim_geo = GeometryText(section_item="Item 8")
    mate_geo = GeometryText(section_item="Item 7")
    claim = _result(
        ("ppe",), totals={"ppe": 6.0}, channels={"ppe": {"context": 6.0}}
    )
    mate = _unclaimed(_score("ppe", 9.0, {"stub": 9.0}))
    results = apply_ppe_vetoes([claim_geo, mate_geo], [claim, mate])
    assert "ppe" not in results[0].claims
    assert _gate_details(results[0]) == ["ppe veto: D1c_true"]
    assert results[1] is mate


def test_context_carried_keeps_same_section_mate():
    claim_geo = GeometryText(section_item="Item 8")
    mate_geo = GeometryText(section_item="Item 8")
    claim = _result(
        ("ppe",), totals={"ppe": 6.0}, channels={"ppe": {"context": 6.0}}
    )
    mate = _unclaimed(_score("ppe", 9.0, {"stub": 9.0}))
    results = apply_ppe_vetoes([claim_geo, mate_geo], [claim, mate])
    assert "ppe" in results[0].claims


def test_context_carried_keeps_signature_earned_claim():
    claim_geo = GeometryText(section_item="Item 8")
    mate_geo = GeometryText(section_item="Item 7")
    claim = _result(
        ("ppe",),
        totals={"ppe": 8.0},
        channels={"ppe": {"context": 6.0, "stub": 2.0}},
    )
    mate = _unclaimed(_score("ppe", 9.0, {"stub": 9.0}))
    results = apply_ppe_vetoes([claim_geo, mate_geo], [claim, mate])
    assert "ppe" in results[0].claims


def test_context_carried_keeps_without_signature_earned_mate():
    claim_geo = GeometryText(section_item="Item 8")
    mate_geo = GeometryText(section_item="Item 7")
    claim = _result(
        ("ppe",), totals={"ppe": 6.0}, channels={"ppe": {"context": 6.0}}
    )
    mate = _unclaimed(_score("ppe", 3.0, {"context": 3.0}))
    results = apply_ppe_vetoes([claim_geo, mate_geo], [claim, mate])
    assert "ppe" in results[0].claims


def test_note_names_every_fired_leg():
    geo = GeometryText(stubs=("Total Assets", "Total Liabilities"))
    results = apply_ppe_vetoes(
        [geo],
        [
            _result(
                ("ppe", "balance_sheet"),
                totals={"ppe": 8.0, "balance_sheet": 9.0},
                channels={"ppe": {"leadin": 4.0, "lead_title": 4.0}},
            )
        ],
    )
    assert "ppe" not in results[0].claims
    assert _gate_details(results[0]) == ["ppe veto: H2claim, LBdomF, L6bal0.4"]


def test_removals_read_the_input_results_only():
    claim_geo = GeometryText(section_item="Item 8")
    mate_geo = GeometryText(section_item="Item 7")
    claim = _result(
        ("ppe",), totals={"ppe": 6.0}, channels={"ppe": {"context": 6.0}}
    )
    mate = _result(
        ("ppe",),
        totals={"ppe": 8.0},
        channels={"ppe": {"leadin": 4.0, "lead_title": 4.0}},
    )
    results = apply_ppe_vetoes([claim_geo, mate_geo], [claim, mate])
    assert "ppe" not in results[0].claims
    assert _gate_details(results[0]) == ["ppe veto: D1c_true"]
    assert "ppe" not in results[1].claims
    assert _gate_details(results[1]) == ["ppe veto: L6bal0.4"]


def test_non_ppe_claims_are_never_removed():
    geo = GeometryText(stubs=("Total Assets", "Total Liabilities"))
    before = [
        _result(
            ("balance_sheet", "inventory"),
            totals={"balance_sheet": 5.0, "inventory": 11.0},
        )
    ]
    results = apply_ppe_vetoes([geo], before)
    assert results == before


def test_unclaimed_geometries_pass_through():
    geo = GeometryText(stubs=("Total Assets", "Total Liabilities"))
    before = [_result(("balance_sheet",), totals={"balance_sheet": 5.0})]
    results = apply_ppe_vetoes([geo], before)
    assert results == before
