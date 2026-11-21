"""FSDS oracle: join classes, segments identity, and the custom branch."""

from __future__ import annotations

from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.engine.xbrl.schema.models import XbrlFact
from edgar_sec.pipelines.xbrl_review.fsds_oracle import (
    FsdsFact,
    FsdsTag,
    compare_panel,
    fsds_fact_from_row,
    fsds_tag_from_row,
)

_A = "0000320193-23-000106"
_B = "0000789019-23-000001"
_STANDARD = FsdsTag(tag="Assets", version="us-gaap/2023", custom=False)


def _fsds(
    accession: str,
    tag: str = "Assets",
    version: str = "us-gaap/2023",
    value: float | None = 100.0,
    segments: str = "",
) -> FsdsFact:
    return FsdsFact(
        accession=accession,
        tag=tag,
        version=version,
        unit="USD",
        period="20230930",
        segments=segments,
        value=value,
    )


def _solver(
    accession: str,
    concept: str = "us-gaap:Assets",
    value: float = 100.0,
    dimensions: dict[str, str] | None = None,
) -> XbrlFact:
    return XbrlFact(
        accession=AccessionNumber(accession),
        concept_qname=concept,
        value=value,
        unit="USD",
        period_type="instant",
        instant_date="2023-09-30",
        dimensions=dimensions or {},
    )


def test_agree_and_totals() -> None:
    report = compare_panel([_fsds(_A)], [_STANDARD], [_solver(_A)])
    assert report.agree == 1
    assert report.diverge == report.facts_only == report.solver_only == 0
    assert report.divergences == ()


def test_diverge_records_both_values() -> None:
    report = compare_panel([_fsds(_A)], [_STANDARD], [_solver(_A, value=101.0)])
    assert report.diverge == 1
    divergence = report.divergences[0]
    assert divergence.fsds_values == (100.0,)
    assert divergence.solver_values == (101.0,)


def test_facts_only_and_solver_only() -> None:
    report = compare_panel(
        [_fsds(_A)],
        [_STANDARD],
        [_solver(_B)],
    )
    assert report.facts_only == 1
    assert report.solver_only == 1


def test_segments_are_fact_identity() -> None:
    report = compare_panel(
        [_fsds(_A, segments="Axis=Member")],
        [_STANDARD],
        [_solver(_A)],
    )
    assert report.agree == 0
    assert report.facts_only == 1
    assert report.solver_only == 1
    matched = compare_panel(
        [_fsds(_A, segments="Axis=Member")],
        [_STANDARD],
        [_solver(_A, dimensions={"Axis": "Member"})],
    )
    assert matched.agree == 1


def test_custom_tag_joins_only_within_its_defining_accession() -> None:
    custom = FsdsTag(tag="MyTag", version=_A, custom=True)
    fact = _fsds(_A, tag="MyTag", version=_A)
    solver = _solver(_A, concept="ext:MyTag")
    report = compare_panel([fact], [custom], [solver])
    assert report.agree == 1


def test_custom_tag_with_foreign_version_is_a_mismatch_not_a_join() -> None:
    custom = FsdsTag(tag="MyTag", version=_A, custom=True)
    fact = _fsds(_B, tag="MyTag", version=_A)
    solver = _solver(_B, concept="ext:MyTag")
    report = compare_panel([fact], [custom], [solver])
    assert report.agree == 0
    assert report.solver_only == 1
    row = report.per_accession[0]
    assert row.accession == _B
    assert row.custom_version_mismatch == 1


def test_unresolved_tag_is_counted_not_joined() -> None:
    report = compare_panel([_fsds(_A)], [], [_solver(_A)])
    assert report.agree == 0
    assert report.solver_only == 1
    assert report.per_accession[0].unresolved_tag == 1


def test_row_adapters_parse_served_text() -> None:
    fact = fsds_fact_from_row(
        {
            "adsh": _A,
            "tag": "Assets",
            "version": "us-gaap/2023",
            "ddate": "20230930",
            "uom": "USD",
            "segments": "",
            "value": "",
        }
    )
    assert fact.value is None
    assert fact.period == "20230930"
    tag = fsds_tag_from_row({"tag": "MyTag", "version": _A, "custom": "1"})
    assert tag.custom is True
    standard = fsds_tag_from_row(
        {"tag": "Assets", "version": "us-gaap/2023", "custom": "0"}
    )
    assert standard == _STANDARD
