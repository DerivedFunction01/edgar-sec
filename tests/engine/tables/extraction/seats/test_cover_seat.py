"""Cover seat: the formation seat on chain-final unclaimed
geometries carrying the cover's own front-matter evidence.
"""

from __future__ import annotations

from edgar_sec.engine.tables.extraction.cascade.filing_competition import (
    compete_filing,
)
from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_scoring import (
    CompetitionResult,
)
from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_text import (
    GeometryText,
)
from edgar_sec.engine.tables.extraction.seats.cover_seat import apply_cover_seat

COV = "cover_layout"


def _result(claims: tuple[str, ...] = ()) -> CompetitionResult:
    return CompetitionResult(claims=claims, contested=(), scores={})


def _seat(geometry: GeometryText, result: CompetitionResult) -> CompetitionResult:
    (out,) = apply_cover_seat([geometry], [result])
    return out


def _registrant_block(**kw: object) -> GeometryText:
    base: dict = {
        "front_matter": True,
        "grid_rows": 2,
        "stubs": ("Delaware",),
        "caption": "(State or other jurisdiction of incorporation or organization)",
    }
    base.update(kw)
    return GeometryText(**base)  # type: ignore[arg-type]


def test_seat_fires_on_a_registrant_block() -> None:
    result = _result()
    out = _seat(_registrant_block(), result)
    assert out.claims == (COV,)
    (group,) = out.groups
    assert group.family == COV
    assert group.state == "reach"
    assert group.score == 0.0
    assert out.scores is result.scores


def test_seat_fires_on_a_class_table() -> None:
    geometry = _registrant_block(
        stubs=(),
        caption="",
        headers=("Title of each class", "Trading Symbol", "Par value"),
    )
    out = _seat(geometry, _result())
    assert out.claims == (COV,)


def test_seat_fires_on_a_checkbox_block_without_vocabulary() -> None:
    geometry = _registrant_block(
        stubs=("Large accelerated filer", "Non-accelerated filer"),
        caption="",
        grid_text="☐ large accelerated filer ☒ non-accelerated filer",
        grid_rows=3,
    )
    out = _seat(geometry, _result())
    assert out.claims == (COV,)


def test_seat_fires_on_the_check_mark_instruction() -> None:
    geometry = _registrant_block(stubs=(), caption="", leadin="check mark")
    out = _seat(geometry, _result())
    assert out.claims == (COV,)


def test_seat_refuses_a_claimed_geometry() -> None:
    result = _result(claims=("balance_sheet",))
    out = _seat(_registrant_block(), result)
    assert out is result


def test_seat_refuses_a_large_grid_in_front_matter() -> None:
    out = _seat(_registrant_block(grid_rows=9), _result())
    assert out.claims == ()


def test_seat_refuses_front_matter_without_cover_evidence() -> None:
    geometry = _registrant_block(stubs=("Minneapolis",), caption="")
    out = _seat(geometry, _result())
    assert out.claims == ()


def test_seat_refuses_a_body_geometry_with_vocabulary() -> None:
    geometry = _registrant_block(front_matter=False, table_index=12)
    out = _seat(geometry, _result())
    assert out.claims == ()


def test_boundary_arm_fires_on_a_mislabeled_registrant_block() -> None:
    geometry = _registrant_block(
        front_matter=False,
        table_index=2,
        caption="Commission File Number: 001-00012",
    )
    out = _seat(geometry, _result())
    assert out.claims == (COV,)


def test_boundary_arm_fires_on_one_term_with_a_checkbox() -> None:
    geometry = _registrant_block(
        front_matter=False,
        table_index=6,
        stubs=("Emerging growth company",),
        caption="",
        grid_text="☐ yes ☒ no",
        grid_rows=3,
    )
    out = _seat(geometry, _result())
    assert out.claims == (COV,)


def test_boundary_arm_refuses_a_checkbox_only_fragment() -> None:
    geometry = _registrant_block(
        front_matter=False,
        table_index=4,
        stubs=("Yes", "No"),
        caption="",
        grid_text="☒ yes ☐ no",
        grid_rows=1,
    )
    out = _seat(geometry, _result())
    assert out.claims == ()


def test_boundary_arm_refuses_a_large_grid() -> None:
    geometry = _registrant_block(front_matter=False, table_index=2, grid_rows=9)
    out = _seat(geometry, _result())
    assert out.claims == ()


def test_boundary_arm_refuses_beyond_the_cover_position() -> None:
    geometry = _registrant_block(front_matter=False, table_index=7)
    out = _seat(geometry, _result())
    assert out.claims == ()


def test_compete_filing_leaves_an_empty_geometry_unclaimed() -> None:
    (out,) = compete_filing([GeometryText()])
    assert out.claims == ()


def test_compete_filing_seats_a_front_matter_cover() -> None:
    geometry = GeometryText(
        front_matter=True,
        grid_rows=2,
        stubs=("Exact name of registrant",),
        caption="Commission File Number: 000-00000",
    )
    (out,) = compete_filing([geometry])
    assert out.claims == (COV,)
