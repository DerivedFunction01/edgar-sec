"""Related-party seat: the formation seat on gate-final
unclaimed geometries whose own heading or stub form carries
the related-party subject over an amount-bearing grid.
"""

from __future__ import annotations

from edgar_sec.engine.tables.extraction.cascade.filing_competition import (
    compete_filing,
)
from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_scoring import (
    CompetitionResult,
    FamilyScore,
)
from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_text import (
    GeometryText,
)
from edgar_sec.engine.tables.extraction.seats.related_party_seat import (
    apply_related_party_seat,
)
from edgar_sec.engine.tables.extraction.separators.summary_separator import (
    SummarySeparatorResult,
)

RP = "related_party"


def _result(
    rp_total: float | None = 3.325,
    claims: tuple[str, ...] = (),
) -> CompetitionResult:
    scores: dict[str, FamilyScore] = {}
    if rp_total is not None:
        scores[RP] = FamilyScore(RP, rp_total, {"leadin": rp_total}, ())
    return CompetitionResult(claims=claims, contested=(), scores=scores)


def _geometry(**kw: object) -> GeometryText:
    base: dict = {
        "stubs": ("Taehoon Kim", "Jaeman Lee", "Total"),
        "lead_title": "— RELATED PARTY TRANSACTIONS",
        "data_rows": 5,
        "numeric_cells": 10,
    }
    base.update(kw)
    return GeometryText(**base)  # type: ignore[arg-type]


def _seat(geometry: GeometryText, result: CompetitionResult) -> CompetitionResult:
    (out,) = apply_related_party_seat([geometry], [result])
    return out


def test_seat_fires_on_the_heading_leg() -> None:
    result = _result()
    out = _seat(_geometry(), result)
    assert out.claims == (RP,)
    (group,) = out.groups
    assert group.family == RP
    assert group.state == "reach"
    assert group.score == 3.325
    assert out.scores is result.scores


def test_seat_fires_on_a_leadin_heading_line() -> None:
    geometry = _geometry(
        lead_title="",
        leadin="Transactions With Related Persons\nSemGroup holds an interest.",
    )
    out = _seat(geometry, _result(0.0))
    assert out.claims == (RP,)
    (group,) = out.groups
    assert group.score == 0.0


def test_seat_fires_on_the_stub_leg() -> None:
    geometry = _geometry(
        lead_title="",
        leadin="With respect to certain jointly-owned policies in force.",
        note_title="– Related party transactions:",
        stubs=(
            "Current receivables from affiliates:",
            "Current payables to affiliates:",
            "Total",
        ),
    )
    out = _seat(geometry, _result(0.0))
    assert out.claims == (RP,)


def test_seat_fires_on_the_relationship_leg() -> None:
    geometry = _geometry(
        lead_title="",
        leadin="The Company has agreements with Vornado, its parent company.",
        note_title="Relationship with Vornado",
        stubs=("Management fees", "Leasing fees", "Total"),
    )
    out = _seat(geometry, _result(0.0))
    assert out.claims == (RP,)


def test_seat_refuses_a_claimed_geometry() -> None:
    result = _result(claims=("balance_sheet",))
    out = _seat(_geometry(), result)
    assert out is result


def test_seat_refuses_a_separator_fired_geometry() -> None:
    geometry = _geometry(
        summary_separator=SummarySeparatorResult(rules=("mda_rows12",))
    )
    out = _seat(geometry, _result())
    assert out.claims == ()


def test_seat_refuses_a_hard_vetoed_geometry() -> None:
    geometry = _geometry(grid_text="for the years ended december 31")
    out = _seat(geometry, _result())
    assert out.claims == ()


def test_seat_refuses_an_oversize_grid() -> None:
    out = _seat(_geometry(data_rows=52, numeric_cells=110), _result())
    assert out.claims == ()


def test_seat_fires_on_a_wide_grid_inside_the_row_bound() -> None:
    out = _seat(_geometry(data_rows=45, numeric_cells=90), _result())
    assert out.claims == (RP,)


def test_seat_fires_past_a_separator_on_corroboration() -> None:
    geometry = _geometry(
        summary_separator=SummarySeparatorResult(rules=("mda_rows12",)),
        stubs=("Due from related parties", "Due to related parties", "Total"),
    )
    out = _seat(geometry, _result())
    assert out.claims == (RP,)


def test_seat_fires_past_a_caption_veto_on_corroboration() -> None:
    geometry = _geometry(
        grid_text="for the years ended december 31",
        stubs=("Due from related parties", "Due to related parties", "Total"),
    )
    out = _seat(geometry, _result())
    assert out.claims == (RP,)


def test_seat_fires_on_the_affiliate_leg() -> None:
    geometry = _geometry(
        lead_title="Amounts due from affiliates",
        stubs=("Due from affiliates", "Due to affiliates", "Total"),
    )
    out = _seat(geometry, _result(0.0))
    assert out.claims == (RP,)


def test_seat_refuses_a_prose_blob_heading() -> None:
    geometry = _geometry(
        lead_title=(
            "The following discussion describes in considerable detail the "
            "various arrangements and understandings that the company has "
            "entered into over the course of the periods presented with a "
            "number of counterparties including certain related party "
            "arrangements that are more fully described in the accompanying "
            "notes to the consolidated financial statements included herein "
            "for the benefit of readers of this annual report on form 10-k "
            "filed with the securities and exchange commission this year"
        ),
    )
    out = _seat(geometry, _result())
    assert out.claims == ()


def test_seat_refuses_without_amounts() -> None:
    out = _seat(_geometry(data_rows=1, numeric_cells=1), _result())
    assert out.claims == ()


def test_seat_refuses_without_a_subject() -> None:
    geometry = _geometry(
        lead_title="Commitments and Contingencies",
        stubs=("AFS securities, at fair value", "Trading securities", "Total"),
    )
    out = _seat(geometry, _result())
    assert out.claims == ()


def test_seat_refuses_stub_form_without_a_subject_title() -> None:
    geometry = _geometry(
        lead_title="",
        leadin="The following table presents amounts due.",
        note_title="Commitments and Contingencies",
        stubs=("Due to related parties", "Total"),
    )
    out = _seat(geometry, _result())
    assert out.claims == ()


def test_seat_refuses_a_prose_mention_off_the_heading_line() -> None:
    geometry = _geometry(
        lead_title="",
        leadin=(
            "Our net invested assets were $189.3 billion as of year end.\n"
            "Investments in related parties are described in the notes."
        ),
        stubs=("AFS securities, at fair value", "Trading securities", "Total"),
    )
    out = _seat(geometry, _result())
    assert out.claims == ()


def test_compete_filing_leaves_a_scoreless_geometry_unclaimed() -> None:
    (out,) = compete_filing([GeometryText()])
    assert out.claims == ()


def test_single_pass_keeps_the_relational_phrases_plural_only() -> None:
    geometry = _geometry(
        lead_title="Amounts from affiliate",
        stubs=("Due to affiliate", "Total"),
    )
    out = _seat(geometry, _result())
    assert out.claims == ()


def test_single_pass_keeps_the_heading_stem_reach() -> None:
    geometry = _geometry(
        lead_title="Balances with related partners",
        stubs=("Taehoon Kim", "Total"),
    )
    out = _seat(geometry, _result())
    assert out.claims == (RP,)


def test_single_pass_never_matches_across_a_stub_boundary() -> None:
    geometry = _geometry(
        lead_title="",
        note_title="Related party transactions",
        stubs=("Due", "to whom it may concern", "Total"),
    )
    out = _seat(geometry, _result())
    assert out.claims == ()
