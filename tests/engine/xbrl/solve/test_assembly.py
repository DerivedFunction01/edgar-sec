"""Tests for cross-filing stitched series assembly."""

from __future__ import annotations

from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.engine.xbrl.schema.models import XbrlFact
from edgar_sec.engine.xbrl.solve.assembly import (
    FYE_CHANGE_REASON,
    TRANSITION_REASON,
    assemble_series,
)
from edgar_sec.engine.xbrl.solve.scoping import FilingRef

_CIK = "7084"
_Q_ORIG = "0000007084-23-000028"
_Q_AMEND = "0000007084-23-000033"
_K21 = "0000007084-22-000040"
_K22 = "0000007084-23-000050"
_K23 = "0000007084-24-000060"
_KT = "0000007084-23-000070"
_K24 = "0000007084-24-000080"
_OUT = "0000007084-24-000099"
_FY21 = ("2021-01-01", "2021-12-31")
_FY22 = ("2022-01-01", "2022-12-31")
_FY23 = ("2023-01-01", "2023-12-31")
_Q2 = ("2023-04-01", "2023-06-30")
_STUB = ("2023-01-01", "2023-06-30")
_FY24_JUN = ("2023-07-01", "2024-06-30")


def _ref(accession: str, form: str, period: str, filed: str) -> FilingRef:
    return FilingRef(
        accession=accession, cik=_CIK, form=form, report_period=period, filed_date=filed
    )


def _fact(
    accession: str,
    qname: str,
    value,
    *,
    span: tuple[str, str] | None = None,
    instant: str | None = None,
    unit: str | None = "USD",
    dimensions: dict | None = None,
) -> XbrlFact:
    return XbrlFact(
        accession=AccessionNumber.from_any(accession),
        concept_qname=qname,
        value=value,
        unit=unit,
        period_type="instant" if instant else "duration",
        start_date=None if instant else (span[0] if span else None),
        end_date=None if instant else (span[1] if span else None),
        instant_date=instant,
        dimensions=dimensions or {},
    )


def _quarter_refs() -> list[FilingRef]:
    return [
        _ref(_Q_ORIG, "10-Q", "2023-06-30", "2023-08-01"),
        _ref(_Q_AMEND, "10-Q/A", "2023-06-30", "2023-11-01"),
        _ref(_K23, "10-K", "2023-12-31", "2024-03-01"),
    ]


def test_assembly_serves_winners_and_retains_superseded() -> None:
    facts = [
        _fact(_Q_ORIG, "us-gaap:NetIncomeLoss", 100.0, span=_Q2),
        _fact(_Q_AMEND, "us-gaap:NetIncomeLoss", 120.0, span=_Q2),
        _fact(_K23, "us-gaap:NetIncomeLoss", 500.0, span=_FY23),
        _fact(_K23, "us-gaap:Assets", 900.0, instant="2023-12-31"),
    ]
    series = assemble_series(_CIK, facts, _quarter_refs())
    assert series.accessions == (_Q_ORIG, _Q_AMEND, _K23)
    winner = series.value("us-gaap:NetIncomeLoss", start_date=_Q2[0], end_date=_Q2[1])
    assert winner is not None
    assert winner.value == 120.0
    assert winner.source_accession == _Q_AMEND
    assert [(item.value, item.superseded_by) for item in series.superseded] == [
        (100.0, _Q_AMEND)
    ]
    # No value exists without a source accession in the selected set.
    assert series.values
    assert all(item.source_accession in series.accessions for item in series.values)
    assert series.breaks == ()


def test_assembly_rereport_precedence_across_filings() -> None:
    refs = [
        _ref(_K22, "10-K", "2022-12-31", "2023-03-01"),
        _ref(_K23, "10-K", "2023-12-31", "2024-03-01"),
    ]
    facts = [
        _fact(_K22, "us-gaap:Revenues", 100.0, span=_FY22),
        _fact(_K23, "us-gaap:Revenues", 110.0, span=_FY22),
        _fact(_K23, "us-gaap:Revenues", 200.0, span=_FY23),
    ]
    series = assemble_series(_CIK, facts, refs)
    winner = series.value("us-gaap:Revenues", start_date=_FY22[0], end_date=_FY22[1])
    assert winner is not None
    assert (winner.value, winner.source_accession) == (110.0, _K23)
    assert [(item.value, item.superseded_by) for item in series.superseded] == [
        (100.0, _K23)
    ]


def test_assembly_transition_filing_breaks_the_series() -> None:
    refs = [
        _ref(_K21, "10-K", "2021-12-31", "2022-03-01"),
        _ref(_K22, "10-K", "2022-12-31", "2023-03-01"),
        _ref(_KT, "10-KT", "2023-06-30", "2023-08-15"),
        _ref(_K24, "10-K", "2024-06-30", "2024-08-20"),
    ]
    facts = [
        _fact(_K21, "us-gaap:Revenues", 1000.0, span=_FY21),
        _fact(_K22, "us-gaap:Revenues", 1100.0, span=_FY22),
        _fact(_KT, "us-gaap:Revenues", 600.0, span=_STUB),
        _fact(_KT, "us-gaap:NetIncomeLoss", 50.0, span=_STUB),
        _fact(_KT, "us-gaap:OperatingIncomeLoss", 80.0, span=_STUB),
        _fact(_K24, "us-gaap:Revenues", 1300.0, span=_FY24_JUN),
    ]
    series = assemble_series(_CIK, facts, refs)
    assert len(series.breaks) == 1
    gap = series.breaks[0]
    assert gap.reason == TRANSITION_REASON
    assert (gap.transition_start, gap.transition_end) == _STUB
    assert gap.after_end == "2022-12-31"
    assert series.segment_count == 2
    # Values on each side are served; the segments do not join across.
    before = {item.value for item in series.segment(0)}
    after = {item.value for item in series.segment(1)}
    assert {1000.0, 1100.0} <= before
    assert {600.0, 1300.0} <= after
    assert len(series.values_for("us-gaap:Revenues")) == 4


def test_assembly_fye_change_without_a_transition_filing_breaks() -> None:
    refs = [
        _ref(_K22, "10-K", "2022-12-31", "2023-03-01"),
        _ref(_K24, "10-K", "2024-06-30", "2024-08-20"),
    ]
    facts = [
        _fact(_K22, "us-gaap:Revenues", 1100.0, span=_FY22),
        _fact(_K24, "us-gaap:Revenues", 1300.0, span=_FY24_JUN),
    ]
    series = assemble_series(_CIK, facts, refs)
    assert len(series.breaks) == 1
    gap = series.breaks[0]
    assert gap.reason == FYE_CHANGE_REASON
    assert gap.after_end == "2022-12-31"
    assert gap.transition_start is None


def test_assembly_week_wobble_in_a_stable_calendar_does_not_break() -> None:
    refs = [
        _ref(_K21, "10-K", "2022-01-29", "2022-03-01"),
        _ref(_K22, "10-K", "2023-02-03", "2023-03-15"),
    ]
    facts = [
        _fact(_K21, "us-gaap:Revenues", 100.0, span=("2021-01-31", "2022-01-29")),
        _fact(_K22, "us-gaap:Revenues", 110.0, span=("2022-01-30", "2023-02-03")),
    ]
    series = assemble_series(_CIK, facts, refs)
    assert series.breaks == ()
    assert series.segment_count == 1


def test_assembly_missing_period_is_honest_absence() -> None:
    facts = [_fact(_K23, "us-gaap:NetIncomeLoss", 500.0, span=_FY23)]
    series = assemble_series(
        _CIK, facts, [_ref(_K23, "10-K", "2023-12-31", "2024-03-01")]
    )
    assert (
        series.value("us-gaap:NetIncomeLoss", start_date=_FY22[0], end_date=_FY22[1])
        is None
    )
    assert series.value("us-gaap:NetIncomeLoss", instant_date="2023-12-31") is None
    assert series.values_for("us-gaap:Revenues") == ()


def test_assembly_excludes_unselected_and_nonnumeric_facts() -> None:
    facts = [
        _fact(_K23, "us-gaap:NetIncomeLoss", 500.0, span=_FY23),
        _fact(_OUT, "us-gaap:NetIncomeLoss", 999.0, span=_FY22),
        _fact(_K23, "dei:DocumentType", "10-K", span=_FY23),
    ]
    series = assemble_series(
        _CIK, facts, [_ref(_K23, "10-K", "2023-12-31", "2024-03-01")]
    )
    assert [item.value for item in series.values] == [500.0]
    assert series.superseded == ()


def test_assembly_same_vintage_duplicates_both_serve() -> None:
    facts = [
        _fact(_K23, "us-gaap:Revenues", 200.0, span=_FY23),
        _fact(_K23, "us-gaap:Revenues", 205.0, span=_FY23),
    ]
    series = assemble_series(
        _CIK, facts, [_ref(_K23, "10-K", "2023-12-31", "2024-03-01")]
    )
    assert {item.value for item in series.values_for("us-gaap:Revenues")} == {
        200.0,
        205.0,
    }
    # The exact-key lookup refuses to pick between the two.
    assert (
        series.value("us-gaap:Revenues", start_date=_FY23[0], end_date=_FY23[1]) is None
    )
