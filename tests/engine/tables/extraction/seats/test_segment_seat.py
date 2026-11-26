"""Segment seat: the formation seat on gate-final unclaimed
geometries whose segment score stays under the claim floor.
"""

from __future__ import annotations

from edgar_sec.engine.tables.extraction.cascade.filing_competition import (
    compete_filing,
)
from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_scoring import (
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
from edgar_sec.engine.tables.extraction.seats.segment_seat import apply_segment_seat
from edgar_sec.engine.tables.extraction.separators.summary_separator import (
    SummarySeparatorResult,
)

SEG = "segment_reporting"


def _core(passed: bool) -> FormTestOutcome:
    return FormTestOutcome(
        family=SEG,
        test_id="segment_reporting_core_form",
        kind="core",
        passed=passed,
        evaluable=True,
        columns_closed=0,
        points=3.0,
        detail="",
    )


def _result(
    seg_total: float | None,
    claims: tuple[str, ...] = (),
    other: float | None = None,
) -> CompetitionResult:
    scores: dict[str, FamilyScore] = {}
    if seg_total is not None:
        scores[SEG] = FamilyScore(SEG, seg_total, {"form_test": seg_total}, ())
    if other is not None:
        scores["income_statement"] = FamilyScore(
            "income_statement", other, {"stub": other}, ()
        )
    return CompetitionResult(claims=claims, contested=(), scores=scores)


def _header_geometry(**kw: object) -> GeometryText:
    base: dict = {
        "stubs": ("apples", "oranges", "bananas"),
        "headers": ("North America", "Europe", "Asia Pacific", "Total"),
        "form_tests": (_core(True),),
    }
    base.update(kw)
    return GeometryText(**base)  # type: ignore[arg-type]


def _seat(geometry: GeometryText, result: CompetitionResult) -> CompetitionResult:
    (out,) = apply_segment_seat([geometry], [result])
    return out


def test_seat_fires_on_the_header_partition_arm() -> None:
    result = _result(4.0, other=3.0)
    out = _seat(_header_geometry(), result)
    assert out.claims == (SEG,)
    (group,) = out.groups
    assert group.family == SEG
    assert group.state == "reach"
    assert group.score == 4.0
    assert out.scores is result.scores


def test_seat_fires_on_the_geographic_partition_arm() -> None:
    geometry = _header_geometry(
        stubs=("United States", "Canada", "Mexico", "Total"),
        headers=("alpha", "beta"),
    )
    out = _seat(geometry, _result(4.0, other=3.0))
    assert out.claims == (SEG,)


def test_seat_fires_on_the_segment_grid() -> None:
    geometry = _header_geometry(
        stubs=("segment revenue", "total segment revenue", "corporate and other"),
        headers=("alpha", "beta"),
    )
    out = _seat(geometry, _result(4.0, other=3.0))
    assert out.claims == (SEG,)


def test_seat_fires_at_the_floor_and_ratio_bounds() -> None:
    out = _seat(_header_geometry(), _result(3.5, other=4.0))
    assert out.claims == (SEG,)
    out = _seat(_header_geometry(), _result(3.75, other=5.0))
    assert out.claims == (SEG,)


def test_seat_refuses_a_claimed_geometry() -> None:
    result = _result(4.0, claims=("income_statement",), other=3.0)
    out = _seat(_header_geometry(), result)
    assert out is result


def test_seat_refuses_a_separator_fired_geometry() -> None:
    geometry = _header_geometry(
        summary_separator=SummarySeparatorResult(rules=("mda_rows12",))
    )
    out = _seat(geometry, _result(4.0, other=3.0))
    assert out.claims == ()


def test_seat_refuses_a_hard_vetoed_geometry() -> None:
    geometry = _header_geometry(
        stubs=("United States", "Canada", "Mexico", "Total"),
        headers=("alpha", "beta"),
        grid_text="page 12",
    )
    out = _seat(geometry, _result(4.0, other=3.0))
    assert out.claims == ()


def test_seat_refuses_below_the_floor() -> None:
    out = _seat(_header_geometry(), _result(3.4, other=1.0))
    assert out.claims == ()


def test_seat_refuses_when_dominance_fails() -> None:
    out = _seat(_header_geometry(), _result(4.0, other=6.0))
    assert out.claims == ()


def test_seat_refuses_without_a_segment_score() -> None:
    out = _seat(_header_geometry(), _result(None, other=1.0))
    assert out.claims == ()


def test_seat_refuses_a_failed_core_form() -> None:
    geometry = _header_geometry(form_tests=(_core(False),))
    out = _seat(geometry, _result(4.0, other=3.0))
    assert out.claims == ()


def test_seat_refuses_an_absent_core_form() -> None:
    geometry = _header_geometry(form_tests=())
    out = _seat(geometry, _result(4.0, other=3.0))
    assert out.claims == ()


def test_seat_refuses_without_corroboration() -> None:
    geometry = _header_geometry(headers=("alpha", "beta"))
    out = _seat(geometry, _result(4.5, other=1.0))
    assert out.claims == ()


def _claimed_source(
    stubs: tuple[str, ...], state: str = "contested"
) -> tuple[GeometryText, CompetitionResult]:
    geometry = GeometryText(stubs=stubs)
    group = ClaimGroup(
        family=SEG,
        score=9.0,
        state=state,
        role="head",
        channels={},
        veto_flags=(),
        explained_foreign=0.0,
    )
    result = CompetitionResult(claims=(SEG,), contested=(), scores={}, groups=(group,))
    return geometry, result


def _name_target(**kw: object) -> GeometryText:
    base: dict = {
        "stubs": ("apples", "oranges"),
        "headers": ("alpha", "beta"),
        "caption": "TABLE 23: Commercial Banking",
        "form_tests": (_core(True),),
    }
    base.update(kw)
    return GeometryText(**base)  # type: ignore[arg-type]


_BANK_SOURCE_STUBS = (
    "Commercial Banking",
    "Consumer and Small Business Banking",
    "Corporate and other",
)


def test_seat_fires_on_the_caption_name_reader_under_the_exception() -> None:
    source_g, source_r = _claimed_source(_BANK_SOURCE_STUBS)
    out = apply_segment_seat(
        [source_g, _name_target()], [source_r, _result(1.5, other=5.21)]
    )
    assert out[0] is source_r
    assert out[1].claims == (SEG,)
    (group,) = out[1].groups
    assert group.state == "reach"


def test_name_exception_still_refuses_a_failed_ratio() -> None:
    source_g, source_r = _claimed_source(_BANK_SOURCE_STUBS)
    out = apply_segment_seat(
        [source_g, _name_target()], [source_r, _result(1.5, other=6.5)]
    )
    assert out[1].claims == ()


def test_name_exception_still_refuses_below_its_floor() -> None:
    source_g, source_r = _claimed_source(_BANK_SOURCE_STUBS)
    out = apply_segment_seat(
        [source_g, _name_target()], [source_r, _result(1.4, other=1.0)]
    )
    assert out[1].claims == ()


def test_no_name_no_exception_at_the_same_scores() -> None:
    source_g, source_r = _claimed_source(_BANK_SOURCE_STUBS)
    target = _name_target(caption="TABLE 23")
    out = apply_segment_seat([source_g, target], [source_r, _result(1.5, other=5.21)])
    assert out[1].claims == ()


def test_seat_adds_do_not_feed_the_vocabulary() -> None:
    source_g, source_r = _claimed_source(_BANK_SOURCE_STUBS, state="reach")
    out = apply_segment_seat(
        [source_g, _name_target()], [source_r, _result(1.5, other=5.21)]
    )
    assert out[1].claims == ()


def test_unit_filtered_stubs_do_not_feed_the_vocabulary() -> None:
    source_g, source_r = _claimed_source(("Commercial Banking in millions",))
    out = apply_segment_seat(
        [source_g, _name_target()], [source_r, _result(1.5, other=5.21)]
    )
    assert out[1].claims == ()


def test_compete_filing_leaves_a_scoreless_geometry_unclaimed() -> None:
    (out,) = compete_filing([GeometryText()])
    assert out.claims == ()
