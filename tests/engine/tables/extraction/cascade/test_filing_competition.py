"""Formation suppression: signature-less PPE claims in
compete_filing's formed set.
"""

from __future__ import annotations

from edgar_sec.engine.tables.extraction.cascade.filing_competition import (
    apply_ppe_formation_suppression,
    apply_ppe_veto_override_seat,
    compete_filing,
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
from edgar_sec.engine.tables.extraction.form_specs.form_test_types import (
    FormTestOutcome,
)


def _group(family: str) -> ClaimGroup:
    return ClaimGroup(
        family=family,
        score=1.0,
        state="claimed",
        role="standalone",
        channels={},
        veto_flags=(),
        explained_foreign=0.0,
    )


def _result(
    claims: tuple[str, ...],
    channels: dict[str, float] | None = None,
    contested: tuple[str, ...] = (),
    groups: tuple[ClaimGroup, ...] = (),
) -> CompetitionResult:
    scores = {}
    if channels is not None:
        scores["ppe"] = FamilyScore("ppe", sum(channels.values()), dict(channels), ())
    return CompetitionResult(
        claims=claims, contested=contested, scores=scores, groups=groups
    )


def _earned() -> CompetitionResult:
    return _result(("ppe",), {"stub": 12.0, "context": 1.0}, groups=(_group("ppe"),))


def _carried() -> CompetitionResult:
    return _result(
        ("ppe", "debt_maturity"),
        {"context": 18.5},
        contested=("ppe",),
        groups=(_group("ppe"), _group("debt_maturity")),
    )


def _blank() -> GeometryText:
    return GeometryText()


def _suppress(
    pairs: list[tuple[GeometryText, CompetitionResult]],
) -> list[CompetitionResult]:
    return apply_ppe_formation_suppression(
        [geometry for geometry, _ in pairs],
        [result for _, result in pairs],
    )


def test_context_only_claim_is_suppressed_beside_an_earned_claim() -> None:
    carried, earned = _carried(), _earned()
    out = _suppress([(_blank(), earned), (_blank(), carried)])
    assert out[0] is earned
    suppressed = out[1]
    assert suppressed.claims == ("debt_maturity",)
    assert suppressed.contested == ()
    assert suppressed.groups == (_group("debt_maturity"),)
    assert suppressed.scores is carried.scores
    assert suppressed.foreign_explained is carried.foreign_explained


def test_context_only_claim_seats_without_an_earned_mate() -> None:
    carried = _carried()
    other = _result(("ppe",), {"context": 9.0})
    out = _suppress([(_blank(), carried), (_blank(), other)])
    assert out == [carried, other]


def test_signature_earned_claims_are_never_suppressed() -> None:
    earned = _earned()
    stub_only = _result(("ppe",), {"stub": 2.0})
    out = _suppress([(_blank(), earned), (_blank(), stub_only)])
    assert out == [earned, stub_only]


def test_zero_signature_channels_still_count_as_signature_less() -> None:
    carried = _result(("ppe",), {"stub": 0.0, "context": 5.0})
    out = _suppress([(_blank(), _earned()), (_blank(), carried)])
    assert out[1].claims == ()


def test_unscored_ppe_claim_counts_as_signature_less() -> None:
    carried = _result(("ppe",), None)
    out = _suppress([(_blank(), _earned()), (_blank(), carried)])
    assert out[1].claims == ()


def test_results_without_ppe_pass_through_untouched() -> None:
    plain = _result(("balance_sheet",))
    out = _suppress([(_blank(), _earned()), (_blank(), plain)])
    assert out[1] is plain
    assert apply_ppe_formation_suppression([], []) == []


def test_sole_depreciation_expense_row_is_spared() -> None:
    # The priced specimens' production surfaces: a sole labeled
    # row, at record data_rows 1 and 2 alike (year-bearing
    # header rows inflate the record count; the labeled-row
    # population is the key).
    for stubs, data_rows in (
        (("Depreciation expense",), 1),
        (("Depreciation expense",), 2),
        (("Depreciation expense (1)",), 2),
    ):
        carried = _carried()
        geometry = GeometryText(stubs=stubs, data_rows=data_rows)
        out = _suppress([(_blank(), _earned()), (geometry, carried)])
        assert out[1] is carried


def test_depreciation_row_among_other_labeled_rows_is_suppressed() -> None:
    for stubs in (
        ("Depreciation expense", "Total"),
        ("Total", "Depreciation expense"),
    ):
        carried = _carried()
        geometry = GeometryText(stubs=stubs, data_rows=2)
        out = _suppress([(_blank(), _earned()), (geometry, carried)])
        assert out[1].claims == ("debt_maturity",)


def test_other_sole_row_labels_are_suppressed() -> None:
    for label in ("Depreciation of assets", "Sparky's Rialto Self-Storage"):
        carried = _carried()
        geometry = GeometryText(stubs=(label,), data_rows=1)
        out = _suppress([(_blank(), _earned()), (geometry, carried)])
        assert out[1].claims == ("debt_maturity",)


_ACQUISITION_GRID = "Costs Capitalized Subsequent to Acquisition"
_BOTH_PASSED = (
    ClaimEvidence("form_test", "ppe_evidence passed", 3.0),
    ClaimEvidence("form_test", "ppe_row_bound passed", 1.0),
)


def _unclaimed(
    total: float,
    channels: dict[str, float],
    evidence: tuple[ClaimEvidence, ...] = (),
) -> CompetitionResult:
    score = FamilyScore("ppe", total, dict(channels), tuple(evidence))
    return CompetitionResult(claims=(), contested=(), scores={"ppe": score})


def _seat(
    pairs: list[tuple[GeometryText, CompetitionResult]],
) -> list[CompetitionResult]:
    return apply_ppe_veto_override_seat(
        [geometry for geometry, _ in pairs],
        [result for _, result in pairs],
    )


def test_leg_f_seats_despite_the_acquisition_veto() -> None:
    result = _unclaimed(2.5, {"form_test": 4.0, "veto": -1.5}, _BOTH_PASSED)
    geometry = GeometryText(grid_text=_ACQUISITION_GRID)
    out = _seat([(geometry, result)])
    assert out[0].claims == ("ppe",)
    group = out[0].groups[-1]
    assert group.family == "ppe"
    assert group.state == "admission"
    assert group.score == 2.5
    assert out[0].scores is result.scores
    assert out[0].foreign_explained is result.foreign_explained


def test_leg_f_seats_with_no_hard_hit() -> None:
    result = _unclaimed(2.5, {"form_test": 4.0}, _BOTH_PASSED)
    out = _seat([(_blank(), result)])
    assert out[0].claims == ("ppe",)


def test_leg_f_needs_both_form_tests() -> None:
    result = _unclaimed(3.0, {"form_test": 3.0}, _BOTH_PASSED[:1])
    geometry = GeometryText(grid_text=_ACQUISITION_GRID)
    out = _seat([(geometry, result)])
    assert out[0] is result


def test_leg_s_seats_on_signature_over_the_veto() -> None:
    channels = {"lead_title": 2.41, "leadin": 2.41, "stub": 2.24, "veto": -1.5}
    evidence = (_BOTH_PASSED[1], ClaimEvidence("veto", "term:lease", -1.5))
    result = _unclaimed(6.56, channels, evidence)
    geometry = GeometryText(grid_text=_ACQUISITION_GRID)
    out = _seat([(geometry, result)])
    assert out[0].claims == ("ppe",)
    assert out[0].groups[-1].state == "admission"


def test_leg_s_needs_the_signature_floor() -> None:
    result = _unclaimed(6.0, {"stub": 4.0, "veto": -1.5})
    geometry = GeometryText(grid_text=_ACQUISITION_GRID)
    out = _seat([(geometry, result)])
    assert out[0] is result


def test_leg_s_needs_the_claim_floor() -> None:
    result = _unclaimed(4.5, {"stub": 7.06, "veto": -2.56})
    geometry = GeometryText(grid_text=_ACQUISITION_GRID)
    out = _seat([(geometry, result)])
    assert out[0] is result


def test_seat_never_displaces_a_claim() -> None:
    claimed = _result(("balance_sheet",), {"stub": 9.0})
    out = _seat([(_blank(), claimed)])
    assert out[0] is claimed
    scored = _unclaimed(2.5, {"form_test": 4.0}, _BOTH_PASSED)
    claimed_ppe = CompetitionResult(claims=("ppe",), contested=(), scores=scored.scores)
    out = _seat([(_blank(), claimed_ppe)])
    assert out[0] is claimed_ppe


def test_seat_passes_unscored_results_through() -> None:
    result = CompetitionResult(claims=(), contested=(), scores={})
    out = _seat([(_blank(), result)])
    assert out[0] is result
    assert apply_ppe_veto_override_seat([], []) == []


def test_seat_group_carries_role_and_veto_flags() -> None:
    evidence = _BOTH_PASSED + (ClaimEvidence("veto", "term:depreciation", -1.5),)
    result = _unclaimed(2.5, {"form_test": 4.0, "veto": -1.5}, evidence)
    geometry = GeometryText(caption="Schedule III", grid_text=_ACQUISITION_GRID)
    out = _seat([(geometry, result)])
    group = out[0].groups[-1]
    assert group.role == "head"
    assert group.veto_flags == ("term:depreciation",)
    assert group.channels == {"form_test": 4.0, "veto": -1.5}


_SCHEDULE_STUBS = (
    "Land",
    "Buildings and improvements",
    "Machinery and equipment",
    "Less accumulated depreciation",
    "Property, plant and equipment, net",
)


def test_leg_d_seats_a_discipline_schedule() -> None:
    result = _unclaimed(12.0, {"stub": 12.0})
    geometry = GeometryText(stubs=_SCHEDULE_STUBS, data_rows=5, numeric_cells=10)
    out = _seat([(geometry, result)])
    assert out[0].claims == ("ppe",)
    assert out[0].groups[-1].state == "admission"


def test_leg_d_seats_the_col1_form() -> None:
    result = _unclaimed(6.6, {"stub": 6.6})
    geometry = GeometryText(
        stubs=("Subscriber system assets, net",),
        headers=("Gross carrying amount", "Accumulated depreciation"),
        grid_text="Accumulated depreciation",
        data_rows=3,
        numeric_cells=6,
    )
    out = _seat([(geometry, result)])
    assert out[0].claims == ("ppe",)


def test_leg_d_seats_classes_carried_in_headers() -> None:
    result = _unclaimed(4.2, {"stub": 4.2})
    geometry = GeometryText(
        stubs=(
            "Additions during period",
            "Reconciliation of accumulated depreciation",
            "Balance at end of period",
        ),
        headers=(
            "SERIES 7",
            "Reconciliation of Land, Building & Improvements",
        ),
        data_rows=15,
        numeric_cells=15,
    )
    out = _seat([(geometry, result)])
    assert out[0].claims == ("ppe",)


def test_leg_d_seats_the_col1_form_carried_in_stubs() -> None:
    result = _unclaimed(6.6, {"stub": 6.6})
    geometry = GeometryText(
        stubs=(
            "Gross carrying amount",
            "Accumulated depreciation",
            "Subscriber system assets, net",
        ),
        headers=("(in thousands)", "September 30, 2018"),
        data_rows=3,
        numeric_cells=6,
    )
    out = _seat([(geometry, result)])
    assert out[0].claims == ("ppe",)


def test_leg_d_refuses_a_balance_sheet_head() -> None:
    result = _unclaimed(20.0, {"stub": 20.0})
    geometry = GeometryText(
        stubs=(
            "ASSETS",
            "Current Assets:",
            "Cash and cash equivalents",
        )
        + _SCHEDULE_STUBS,
        data_rows=9,
        numeric_cells=30,
    )
    out = _seat([(geometry, result)])
    assert out[0] is result


def test_leg_d_refuses_a_balance_sheet_title() -> None:
    result = _unclaimed(20.0, {"stub": 20.0})
    geometry = GeometryText(
        stubs=("Condensed Consolidated Balance Sheets",) + _SCHEDULE_STUBS,
        data_rows=9,
        numeric_cells=30,
    )
    out = _seat([(geometry, result)])
    assert out[0] is result


def test_leg_d_needs_a_positive_score() -> None:
    result = _unclaimed(0.0, {"stub": 0.0})
    geometry = GeometryText(stubs=_SCHEDULE_STUBS, data_rows=5, numeric_cells=10)
    out = _seat([(geometry, result)])
    assert out[0] is result


def test_leg_d_needs_two_classes() -> None:
    result = _unclaimed(9.0, {"stub": 9.0})
    geometry = GeometryText(
        stubs=("Land", "Less accumulated depreciation"),
        data_rows=3,
        numeric_cells=6,
    )
    out = _seat([(geometry, result)])
    assert out[0] is result


def test_leg_d_needs_numeric_mass() -> None:
    result = _unclaimed(9.0, {"stub": 9.0})
    geometry = GeometryText(stubs=_SCHEDULE_STUBS, data_rows=1, numeric_cells=1)
    out = _seat([(geometry, result)])
    assert out[0] is result


def test_compete_filing_seats_the_vetoed_schedule() -> None:
    outcomes = (
        FormTestOutcome("ppe", "ppe_evidence", "form", True, True, 0, 3.0, ""),
        FormTestOutcome("ppe", "ppe_row_bound", "form", True, True, 0, 1.0, ""),
    )
    geometry = GeometryText(
        stubs=("Elm Street Apartments", "Oak Plaza"),
        grid_text=_ACQUISITION_GRID,
        form_tests=outcomes,
    )
    out = compete_filing([geometry])
    assert out[0].claims == ("ppe",)
    assert out[0].groups[-1].state == "admission"
