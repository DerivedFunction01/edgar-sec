"""Tests for YTD un-accumulation over a stitched series."""

from __future__ import annotations

from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.engine.xbrl.schema.models import XbrlFact
from edgar_sec.engine.xbrl.solve.assembly import assemble_series
from edgar_sec.engine.xbrl.solve.query import QueryStatus
from edgar_sec.engine.xbrl.solve.scoping import FilingRef
from edgar_sec.engine.xbrl.solve.stitched import DERIVED_EXACT_BASIS
from edgar_sec.engine.xbrl.solve.unaccumulate import (
    AMBIGUOUS_LEG,
    CROSSES_SERIES_BREAK,
    MISSING_PRIOR_LEG,
    derive_discrete_quarters,
)

_CIK = "7084"
_Q1 = "0000007084-23-000010"
_Q2 = "0000007084-23-000020"
_Q3 = "0000007084-23-000030"
_K = "0000007084-24-000040"
_KT = "0000007084-23-000050"
_REV = "us-gaap:Revenues"
_FY = "2023-01-01"
_Q1_SPAN = ("2023-01-01", "2023-03-31")
_YTD2_SPAN = ("2023-01-01", "2023-06-30")
_YTD3_SPAN = ("2023-01-01", "2023-09-30")
_FY_SPAN = ("2023-01-01", "2023-12-31")
_Q2_SPAN = ("2023-04-01", "2023-06-30")
_Q3_SPAN = ("2023-07-01", "2023-09-30")
_Q4_SPAN = ("2023-10-01", "2023-12-31")
_STUB = ("2023-07-01", "2023-12-31")


def _ref(accession: str, form: str, period: str, filed: str) -> FilingRef:
    return FilingRef(
        accession=accession, cik=_CIK, form=form, report_period=period, filed_date=filed
    )


def _fact(
    accession: str,
    qname: str,
    value,
    *,
    span: tuple[str, str],
    unit: str | None = "USD",
    dimensions: dict | None = None,
) -> XbrlFact:
    return XbrlFact(
        accession=AccessionNumber.from_any(accession),
        concept_qname=qname,
        value=value,
        unit=unit,
        period_type="duration",
        start_date=span[0],
        end_date=span[1],
        instant_date=None,
        dimensions=dimensions or {},
    )


def _ytd_refs() -> list[FilingRef]:
    return [
        _ref(_Q1, "10-Q", "2023-03-31", "2023-05-01"),
        _ref(_Q2, "10-Q", "2023-06-30", "2023-08-01"),
        _ref(_Q3, "10-Q", "2023-09-30", "2023-11-01"),
        _ref(_K, "10-K", "2023-12-31", "2024-03-01"),
    ]


def _ytd_facts() -> list[XbrlFact]:
    """A YTD-only filer: Q1 as a quarter, then cumulative spans only."""
    return [
        _fact(_Q1, _REV, 100.0, span=_Q1_SPAN),
        _fact(_Q2, _REV, 300.0, span=_YTD2_SPAN),
        _fact(_Q3, _REV, 550.0, span=_YTD3_SPAN),
        _fact(_K, _REV, 800.0, span=_FY_SPAN),
    ]


def _by_span(result) -> dict[tuple[str, str], object]:
    return {(item.start_date, item.end_date): item for item in result.derived}


def test_ytd_only_filer_derives_hand_computed_quarters() -> None:
    series = assemble_series(_CIK, _ytd_facts(), _ytd_refs())
    result = derive_discrete_quarters(series)
    assert result.refusals == ()
    derived = _by_span(result)
    assert set(derived) == {_Q2_SPAN, _Q3_SPAN, _Q4_SPAN}
    assert derived[_Q2_SPAN].value == 200.0
    assert derived[_Q3_SPAN].value == 250.0
    assert derived[_Q4_SPAN].value == 250.0
    for item in result.derived:
        assert item.status == QueryStatus.DERIVED
        assert item.basis == DERIVED_EXACT_BASIS
    q2 = derived[_Q2_SPAN]
    assert q2.source_accession == _Q2
    assert [item.accession for item in q2.derivation_inputs] == [_Q1, _Q2]
    assert [item.value for item in q2.derivation_inputs] == [100.0, 300.0]
    q4 = derived[_Q4_SPAN]
    assert [item.accession for item in q4.derivation_inputs] == [_Q3, _K]


def test_reported_quarter_wins_over_derived() -> None:
    facts = _ytd_facts() + [_fact(_Q2, _REV, 200.0, span=_Q2_SPAN)]
    series = assemble_series(_CIK, facts, _ytd_refs())
    result = derive_discrete_quarters(series)
    assert result.refusals == ()
    assert set(_by_span(result)) == {_Q3_SPAN, _Q4_SPAN}
    winner = series.value(_REV, start_date=_Q2_SPAN[0], end_date=_Q2_SPAN[1])
    assert winner is not None and winner.value == 200.0


def test_missing_prior_leg_refuses_only_that_quarter() -> None:
    facts = [fact for fact in _ytd_facts() if fact.end_date != "2023-03-31"]
    series = assemble_series(_CIK, facts, _ytd_refs())
    result = derive_discrete_quarters(series)
    assert set(_by_span(result)) == {_Q3_SPAN, _Q4_SPAN}
    assert len(result.refusals) == 1
    refusal = result.refusals[0]
    assert refusal.reason == MISSING_PRIOR_LEG
    assert (refusal.start_date, refusal.end_date) == _YTD2_SPAN


def test_restated_leg_is_the_derivation_input() -> None:
    facts = _ytd_facts() + [_fact(_Q3, _REV, 310.0, span=_YTD2_SPAN)]
    series = assemble_series(_CIK, facts, _ytd_refs())
    result = derive_discrete_quarters(series)
    q2 = _by_span(result)[_Q2_SPAN]
    assert q2.value == 210.0
    assert [item.accession for item in q2.derivation_inputs] == [_Q1, _Q3]


def test_chain_refuses_across_a_series_break() -> None:
    refs = _ytd_refs() + [_ref(_KT, "10-KT", "2023-12-31", "2023-12-15")]
    facts = _ytd_facts() + [
        _fact(_KT, _REV, 250.0, span=_STUB),
        _fact(_KT, "us-gaap:NetIncomeLoss", 40.0, span=_STUB),
        _fact(_KT, "us-gaap:OperatingIncomeLoss", 60.0, span=_STUB),
    ]
    series = assemble_series(_CIK, facts, refs)
    assert len(series.breaks) == 1
    result = derive_discrete_quarters(series)
    assert _Q2_SPAN in _by_span(result)
    reasons = {(item.end_date, item.reason) for item in result.refusals}
    assert ("2023-09-30", CROSSES_SERIES_BREAK) in reasons


def test_unit_mismatch_breaks_the_chain() -> None:
    facts = [
        _fact(_Q1, _REV, 100.0, span=_Q1_SPAN),
        _fact(_Q2, _REV, 300.0, span=_YTD2_SPAN),
        _fact(_Q3, _REV, 550.0, span=_YTD3_SPAN),
        _fact(_K, _REV, 800.0, span=_FY_SPAN, unit="EUR"),
    ]
    series = assemble_series(_CIK, facts, _ytd_refs())
    result = derive_discrete_quarters(series)
    assert set(_by_span(result)) == {_Q2_SPAN, _Q3_SPAN}
    assert len(result.refusals) == 1
    refusal = result.refusals[0]
    assert refusal.reason == MISSING_PRIOR_LEG
    assert refusal.unit == "EUR"


def test_dimensioned_legs_form_their_own_chain() -> None:
    dims = {"us-gaap:ProductMember": "x"}
    facts = _ytd_facts() + [
        _fact(_Q2, _REV, 300.0, span=_YTD2_SPAN, dimensions=dims),
    ]
    series = assemble_series(_CIK, facts, _ytd_refs())
    result = derive_discrete_quarters(series)
    assert set(_by_span(result)) == {_Q2_SPAN, _Q3_SPAN, _Q4_SPAN}
    assert len(result.refusals) == 1
    refusal = result.refusals[0]
    assert refusal.reason == MISSING_PRIOR_LEG
    assert dict(refusal.dimensions) == dims


def test_duplicate_leg_is_ambiguous_and_refused() -> None:
    facts = _ytd_facts() + [_fact(_Q2, _REV, 305.0, span=_YTD2_SPAN)]
    series = assemble_series(_CIK, facts, _ytd_refs())
    result = derive_discrete_quarters(series)
    assert _Q2_SPAN not in _by_span(result)
    assert _Q3_SPAN not in _by_span(result)
    assert {item.reason for item in result.refusals} == {AMBIGUOUS_LEG}
