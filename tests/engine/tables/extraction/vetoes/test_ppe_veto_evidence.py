"""PPE veto pass: the seven priced legs, dominance priced
on the pre-gate claim stage."""

from __future__ import annotations

from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_text import (
    GeometryText,
)
from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_scoring import (
    ClaimEvidence,
    ClaimGroup,
    CompetitionResult,
    FamilyScore,
)
from edgar_sec.engine.tables.extraction.vetoes.ppe_veto_evidence import (
    ClaimStage,
    apply_ppe_vetoes,
    capture_claim_stages,
)
from edgar_sec.engine.tables.extraction.vetoes.ppe_veto_specs import (
    SIGNATURE_CHANNELS,
    STRONG_STUB_KEYS,
)
from edgar_sec.engine.tables.extraction.core.subjects.signature_profiles import CHANNELS


def _score(family, total=11.0, channels=None):
    return FamilyScore(family, total, channels or {"stub": total}, ())


def _result(families, totals=None, channels=None, groups=()):
    totals = totals or {}
    channels = channels or {}
    scores = {
        family: _score(family, totals.get(family, 11.0), channels.get(family))
        for family in families
    }
    return CompetitionResult(
        claims=tuple(families),
        contested=tuple(families),
        scores=scores,
        groups=groups,
    )


def _apply(geometries, results):
    stages = tuple(
        ClaimStage(claims=result.claims, scores=result.scores) for result in results
    )
    return apply_ppe_vetoes(geometries, results, stages)


def _unclaimed(score):
    return CompetitionResult(claims=(), contested=(), scores={"ppe": score})


def _gate_details(result, family="ppe"):
    return [
        item.detail for item in result.scores[family].evidence if item.channel == "gate"
    ]


def test_specs_carry_the_arbitrated_strong_sets():
    assert len(STRONG_STUB_KEYS) == 11
    assert sum(len(keys) for keys in STRONG_STUB_KEYS.values()) == 22
    assert "total assets" in STRONG_STUB_KEYS["balance_sheet"]
    assert "ppe" not in STRONG_STUB_KEYS


def test_host_claim_no_longer_removes_ppe_on_two_shared_keys():
    geo = GeometryText(stubs=("Total Assets", "Total Liabilities", "Land"))
    groups = (
        ClaimGroup("ppe", 11.0, "claimed", "primary", {"stub": 11.0}, (), 0.0),
        ClaimGroup("balance_sheet", 5.0, "claimed", "primary", {"stub": 5.0}, (), 0.0),
    )
    results = _apply(
        [geo],
        [
            _result(
                ("ppe", "balance_sheet"),
                totals={"balance_sheet": 5.0},
                groups=groups,
            )
        ],
    )
    assert "ppe" in results[0].claims
    assert "balance_sheet" in results[0].claims
    assert results[0].scores["ppe"].total == 11.0
    assert _gate_details(results[0]) == []
    assert [group.family for group in results[0].groups] == [
        "ppe",
        "balance_sheet",
    ]


def test_host_claim_needs_two_shared_keys():
    geo = GeometryText(stubs=("Total Assets", "Land"))
    results = _apply(
        [geo],
        [_result(("ppe", "balance_sheet"), totals={"balance_sheet": 5.0})],
    )
    assert "ppe" in results[0].claims


def test_host_claim_needs_the_host_claiming():
    geo = GeometryText(stubs=("Total Assets", "Total Liabilities"))
    results = _apply([geo], [_result(("ppe",))])
    assert "ppe" in results[0].claims


def test_dominance_no_longer_removes_on_a_tie():
    geo = GeometryText()
    results = _apply([geo], [_result(("ppe", "inventory"), totals={"inventory": 11.0})])
    assert "ppe" in results[0].claims
    assert _gate_details(results[0]) == []


def test_dominance_keeps_below_the_tie():
    geo = GeometryText()
    results = _apply([geo], [_result(("ppe", "inventory"), totals={"inventory": 10.5})])
    assert "ppe" in results[0].claims


def test_lead_balance_removes_on_balanced_prose():
    geo = GeometryText()
    results = _apply(
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
    results = _apply(
        [geo],
        [
            _result(
                ("ppe",),
                totals={"ppe": 8.0},
                channels={"ppe": {"leadin": 2.0, "lead_title": 6.0}},
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
        results = _apply(
            [geo],
            [_result(("ppe",), totals={"ppe": 8.0}, channels={"ppe": channels})],
        )
        assert "ppe" in results[0].claims


def test_context_carried_removes_with_cross_section_mate():
    claim_geo = GeometryText(stubs=("Land", "Building"), section_item="Item 8")
    mate_geo = GeometryText(section_item="Item 7")
    claim = _result(("ppe",), totals={"ppe": 6.0}, channels={"ppe": {"context": 6.0}})
    mate = _unclaimed(_score("ppe", 9.0, {"stub": 9.0}))
    results = _apply([claim_geo, mate_geo], [claim, mate])
    assert "ppe" not in results[0].claims
    assert _gate_details(results[0]) == ["ppe veto: D1c_true"]
    assert results[1] is mate


def test_context_carried_keeps_same_section_mate():
    claim_geo = GeometryText(stubs=("Land", "Building"), section_item="Item 8")
    mate_geo = GeometryText(section_item="Item 8")
    claim = _result(("ppe",), totals={"ppe": 6.0}, channels={"ppe": {"context": 6.0}})
    mate = _unclaimed(_score("ppe", 9.0, {"stub": 9.0}))
    results = _apply([claim_geo, mate_geo], [claim, mate])
    assert "ppe" in results[0].claims


def test_context_carried_keeps_signature_earned_claim():
    claim_geo = GeometryText(stubs=("Land", "Building"), section_item="Item 8")
    mate_geo = GeometryText(section_item="Item 7")
    claim = _result(
        ("ppe",),
        totals={"ppe": 8.0},
        channels={"ppe": {"context": 6.0, "stub": 2.0}},
    )
    mate = _unclaimed(_score("ppe", 9.0, {"stub": 9.0}))
    results = _apply([claim_geo, mate_geo], [claim, mate])
    assert "ppe" in results[0].claims


def test_context_carried_keeps_without_signature_earned_mate():
    claim_geo = GeometryText(stubs=("Land", "Building"), section_item="Item 8")
    mate_geo = GeometryText(section_item="Item 7")
    claim = _result(("ppe",), totals={"ppe": 6.0}, channels={"ppe": {"context": 6.0}})
    mate = _unclaimed(_score("ppe", 3.0, {"context": 3.0}))
    results = _apply([claim_geo, mate_geo], [claim, mate])
    assert "ppe" in results[0].claims


def test_note_names_every_fired_leg():
    geo = GeometryText(stubs=("Total Assets", "Total Liabilities"))
    results = _apply(
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
    assert _gate_details(results[0]) == ["ppe veto: L6bal0.4, AcoexLead"]


def test_removals_read_the_input_results_only():
    claim_geo = GeometryText(stubs=("Land", "Building"), section_item="Item 8")
    mate_geo = GeometryText(section_item="Item 7")
    claim = _result(("ppe",), totals={"ppe": 6.0}, channels={"ppe": {"context": 6.0}})
    mate = _result(
        ("ppe",),
        totals={"ppe": 8.0},
        channels={"ppe": {"leadin": 4.0, "lead_title": 4.0}},
    )
    results = _apply([claim_geo, mate_geo], [claim, mate])
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
    results = _apply([geo], before)
    assert results == before


def test_unclaimed_geometries_pass_through():
    geo = GeometryText(stubs=("Total Assets", "Total Liabilities"))
    before = [_result(("balance_sheet",), totals={"balance_sheet": 5.0})]
    results = _apply([geo], before)
    assert results == before


def test_signature_channels_are_the_homed_channels():
    assert SIGNATURE_CHANNELS is CHANNELS


def test_dominance_leg_is_retired_a_stage_rival_does_not_remove():
    geo = GeometryText()
    final = _result(("ppe",), totals={"ppe": 11.0})
    stage = ClaimStage(
        claims=("ppe", "inventory"),
        scores={"inventory": _score("inventory", 11.0)},
    )
    results = apply_ppe_vetoes([geo], [final], [stage])
    assert "ppe" in results[0].claims
    assert _gate_details(results[0]) == []


def test_dominance_ignores_a_rival_absent_at_the_stage():
    geo = GeometryText()
    final = _result(("ppe", "inventory"), totals={"inventory": 12.0})
    stage = ClaimStage(claims=("ppe",), scores={"ppe": _score("ppe", 11.0)})
    results = apply_ppe_vetoes([geo], [final], [stage])
    assert "ppe" in results[0].claims


def test_capture_claim_stages_unions_claims_keeps_own_scores():
    own = _result(("ppe", "inventory"))
    mid = _result(("ppe", "balance_sheet"))
    stages = capture_claim_stages([own], [mid])
    assert stages[0].claims == ("ppe", "inventory", "balance_sheet")
    assert stages[0].scores is own.scores


def test_weak_signature_removes_weak_single_class():
    geo = GeometryText(stubs=("Land",))
    results = _apply(
        [geo],
        [_result(("ppe",), totals={"ppe": 3.0}, channels={"ppe": {"stub": 3.0}})],
    )
    assert "ppe" not in results[0].claims
    assert _gate_details(results[0]) == ["ppe veto: B6sig5div1"]


def test_weak_signature_keeps_diverse_classes():
    geo = GeometryText(stubs=("Land", "Building", "Equipment"))
    results = _apply(
        [geo],
        [_result(("ppe",), totals={"ppe": 3.0}, channels={"ppe": {"stub": 3.0}})],
    )
    assert "ppe" in results[0].claims


def test_weak_signature_keeps_strong_signature():
    geo = GeometryText(stubs=("Land",))
    results = _apply(
        [geo],
        [_result(("ppe",), totals={"ppe": 7.0}, channels={"ppe": {"stub": 7.0}})],
    )
    assert "ppe" in results[0].claims


def test_coex_lead_removes_lead_only_with_rival():
    geo = GeometryText(stubs=("Unfunded commitments",))
    results = _apply(
        [geo],
        [
            _result(
                ("ppe", "commitments_contingencies"),
                totals={"ppe": 11.0, "commitments_contingencies": 5.0},
                channels={"ppe": {"leadin": 4.83, "lead_title": 2.41}},
            )
        ],
    )
    assert "ppe" not in results[0].claims
    assert _gate_details(results[0]) == ["ppe veto: AcoexLead"]


def test_coex_lead_keeps_stub_earned_signature():
    geo = GeometryText(stubs=("Unfunded commitments",))
    results = _apply(
        [geo],
        [
            _result(
                ("ppe", "commitments_contingencies"),
                totals={"ppe": 11.0, "commitments_contingencies": 5.0},
                channels={"ppe": {"leadin": 4.83, "lead_title": 2.41, "stub": 1.0}},
            )
        ],
    )
    assert "ppe" in results[0].claims


def test_coex_lead_keeps_without_rival():
    geo = GeometryText(stubs=("Unfunded commitments",))
    results = _apply(
        [geo],
        [
            _result(
                ("ppe",),
                totals={"ppe": 11.0},
                channels={"ppe": {"leadin": 4.83, "lead_title": 2.41}},
            )
        ],
    )
    assert "ppe" in results[0].claims


def test_statement_form_removes_statement_length():
    geo = GeometryText(data_rows=34, numeric_cells=102)
    results = _apply(
        [geo],
        [_result(("ppe",), totals={"ppe": 9.0}, channels={"ppe": {"stub": 9.0}})],
    )
    assert "ppe" not in results[0].claims
    assert _gate_details(results[0]) == ["ppe veto: Bstmt30x100"]


def test_statement_form_keeps_below_either_threshold():
    for geo in (
        GeometryText(data_rows=34, numeric_cells=99),
        GeometryText(data_rows=29, numeric_cells=102),
    ):
        results = _apply(
            [geo],
            [
                _result(
                    ("ppe",),
                    totals={"ppe": 9.0},
                    channels={"ppe": {"stub": 9.0}},
                )
            ],
        )
        assert "ppe" in results[0].claims


def test_note_names_the_new_legs_in_order():
    geo = GeometryText(stubs=("Land",), data_rows=30, numeric_cells=100)
    results = _apply(
        [geo],
        [_result(("ppe",), totals={"ppe": 3.0}, channels={"ppe": {"stub": 3.0}})],
    )
    assert "ppe" not in results[0].claims
    assert _gate_details(results[0]) == ["ppe veto: B6sig5div1, Bstmt30x100"]


_BOTH_PASSED = (
    ClaimEvidence("form_test", "ppe_evidence passed", 3.0),
    ClaimEvidence("form_test", "ppe_row_bound passed", 1.0),
)


def _seated_result(total, channels, evidence, state="admission", families=("ppe",)):
    scores = {
        "ppe": FamilyScore("ppe", total, dict(channels), tuple(evidence)),
    }
    groups = [ClaimGroup("ppe", total, state, "standalone", dict(channels), (), 0.0)]
    for family in families:
        if family == "ppe":
            continue
        scores[family] = _score(family, 2.0)
        groups.append(ClaimGroup(family, 2.0, "claimed", "standalone", {}, (), 0.0))
    return CompetitionResult(
        claims=tuple(families),
        contested=(),
        scores=scores,
        groups=tuple(groups),
    )


def test_packet_legs_skip_a_form_test_admission_seat():
    geo = GeometryText(stubs=("Land",))
    results = _apply([geo], [_seated_result(3.0, {"stub": 3.0}, _BOTH_PASSED)])
    assert "ppe" in results[0].claims
    assert _gate_details(results[0]) == []


def test_packet_legs_skip_statement_form_on_an_admission_seat():
    geo = GeometryText(data_rows=34, numeric_cells=102)
    results = _apply([geo], [_seated_result(9.0, {"stub": 9.0}, _BOTH_PASSED)])
    assert "ppe" in results[0].claims
    assert _gate_details(results[0]) == []


_DISCIPLINE_STUBS = (
    "Land",
    "Buildings and improvements",
    "Machinery and equipment",
    "Less accumulated depreciation",
    "Property, plant and equipment, net",
)


def test_packet_legs_skip_statement_form_on_a_discipline_seat():
    geo = GeometryText(stubs=_DISCIPLINE_STUBS, data_rows=34, numeric_cells=102)
    results = _apply([geo], [_seated_result(9.0, {"stub": 9.0}, ())])
    assert "ppe" in results[0].claims
    assert _gate_details(results[0]) == []


def test_discipline_skip_needs_the_admission_state():
    geo = GeometryText(stubs=_DISCIPLINE_STUBS, data_rows=34, numeric_cells=102)
    seated = _seated_result(9.0, {"stub": 9.0}, (), state="claimed")
    results = _apply([geo], [seated])
    assert "ppe" not in results[0].claims
    assert _gate_details(results[0]) == ["ppe veto: Bstmt30x100"]


def test_skip_needs_both_form_tests_passed():
    geo = GeometryText(stubs=("Land",))
    results = _apply([geo], [_seated_result(3.0, {"stub": 3.0}, _BOTH_PASSED[1:])])
    assert "ppe" not in results[0].claims
    assert _gate_details(results[0]) == ["ppe veto: B6sig5div1"]


def test_skip_needs_the_admission_state():
    geo = GeometryText(stubs=("Land",))
    seated = _seated_result(3.0, {"stub": 3.0}, _BOTH_PASSED, state="claimed")
    results = _apply([geo], [seated])
    assert "ppe" not in results[0].claims
    assert _gate_details(results[0]) == ["ppe veto: B6sig5div1"]


def test_retired_legs_do_not_fire_on_an_admission_seat():
    geo = GeometryText(stubs=("Total Assets", "Total Liabilities", "Land"))
    seated = _seated_result(
        3.0, {"stub": 3.0}, _BOTH_PASSED, families=("ppe", "balance_sheet")
    )
    results = _apply([geo], [seated])
    assert "ppe" in results[0].claims
    assert _gate_details(results[0]) == []
