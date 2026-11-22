"""Formation suppression: signature-less PPE claims in
compete_filing's formed set.
"""

from __future__ import annotations

from edgar_sec.engine.tables.extraction.cascade.filing_competition import (
    apply_ppe_formation_suppression,
)
from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_scoring import (
    ClaimGroup,
    CompetitionResult,
    FamilyScore,
)
from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_text import (
    GeometryText,
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
