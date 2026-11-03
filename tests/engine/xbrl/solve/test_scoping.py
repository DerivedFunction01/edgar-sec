"""Tests for fact scoping, amendment lineage, and supersession."""

from __future__ import annotations

from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.engine.xbrl.schema.models import XbrlFact
from edgar_sec.engine.xbrl.solve.scoping import (
    FactScope,
    FilingRef,
    base_form,
    build_lineages,
    covering_lineage,
    is_amendment_form,
    supersede_facts,
)

_ORIG = "0000007084-23-000028"
_AMEND = "0000007084-23-000033"
_AMEND2 = "0000007084-23-000041"
_OTHER = "0000019617-23-000270"


def _ref(accession: str, form: str, period: str, filed: str, cik: str = "7084"):
    return FilingRef(
        accession=accession, cik=cik, form=form, report_period=period, filed_date=filed
    )


def _lineage():
    return build_lineages(
        [
            _ref(_AMEND, "10-Q/A", "2023-06-30", "2023-11-01"),
            _ref(_ORIG, "10-Q", "2023-06-30", "2023-08-01"),
        ]
    )[0]


def _fact(
    accession: str,
    qname: str,
    value: float,
    *,
    start: str | None = "2023-04-01",
    end: str | None = "2023-06-30",
    instant: str | None = None,
    dimensions: dict | None = None,
) -> XbrlFact:
    return XbrlFact(
        accession=AccessionNumber.from_any(accession),
        concept_qname=qname,
        value=value,
        unit="USD",
        period_type="instant" if instant else "duration",
        start_date=None if instant else start,
        end_date=None if instant else end,
        instant_date=instant,
        dimensions=dimensions or {},
    )


def test_base_form_strips_only_the_amendment_suffix() -> None:
    assert base_form("10-Q/A") == "10-Q"
    assert base_form("10-K") == "10-K"
    assert is_amendment_form("10-Q/A")
    assert not is_amendment_form("10-Q")


def test_build_lineages_groups_by_cik_form_and_period() -> None:
    lineages = build_lineages(
        [
            _ref(_AMEND, "10-Q/A", "2023-06-30", "2023-11-01"),
            _ref(_ORIG, "10-Q", "2023-06-30", "2023-08-01"),
            _ref(_OTHER, "10-Q", "2023-06-30", "2023-08-02", cik="19617"),
            _ref("0000007084-23-000099", "10-Q/A", "2023-09-30", "2024-01-05"),
            _ref("0000007084-24-000001", "10-K/A", "2023-06-30", "2024-02-01"),
        ]
    )
    # The other-cik original forms no lineage; the two amendment-only
    # groups (a different period, a different base form) stand alone.
    assert len(lineages) == 3
    lineage = next(item for item in lineages if len(item.accessions) == 2)
    assert lineage.cik == "7084"
    assert lineage.form == "10-Q"
    assert lineage.report_period == "2023-06-30"
    # The original ranks first even though the amendment was listed first.
    assert lineage.accessions == (_ORIG, _AMEND)
    assert lineage.original == _ORIG
    assert lineage.latest == _AMEND
    assert lineage.rank(_AMEND) == 1
    assert lineage.rank(_OTHER) is None


def test_build_lineages_orders_multiple_amendments_by_filed_date() -> None:
    lineages = build_lineages(
        [
            _ref(_AMEND2, "10-Q/A", "2023-06-30", "2024-02-01"),
            _ref(_ORIG, "10-Q", "2023-06-30", "2023-08-01"),
            _ref(_AMEND, "10-Q/A", "2023-06-30", "2023-11-01"),
        ]
    )
    assert lineages[0].accessions == (_ORIG, _AMEND, _AMEND2)


def test_supersede_facts_restated_key_answers_from_amendment() -> None:
    lineage = _lineage()
    original = _fact(_ORIG, "us-gaap:NetIncomeLoss", 100.0)
    restated = _fact(_AMEND, "us-gaap:NetIncomeLoss", 120.0)
    standing = _fact(_ORIG, "us-gaap:Assets", 900.0, instant="2023-06-30")
    resolved = supersede_facts([original, restated, standing], [lineage])
    assert resolved == (restated, standing)


def test_supersede_facts_dimensions_make_distinct_keys() -> None:
    lineage = _lineage()
    plain = _fact(_ORIG, "us-gaap:Revenues", 10.0)
    segmented = _fact(_AMEND, "us-gaap:Revenues", 4.0, dimensions={"axis": "product"})
    resolved = supersede_facts([plain, segmented], [lineage])
    assert resolved == (plain, segmented)


def test_supersede_facts_latest_amendment_wins() -> None:
    lineages = build_lineages(
        [
            _ref(_ORIG, "10-Q", "2023-06-30", "2023-08-01"),
            _ref(_AMEND, "10-Q/A", "2023-06-30", "2023-11-01"),
            _ref(_AMEND2, "10-Q/A", "2023-06-30", "2024-02-01"),
        ]
    )
    facts = [
        _fact(_ORIG, "us-gaap:NetIncomeLoss", 100.0),
        _fact(_AMEND, "us-gaap:NetIncomeLoss", 120.0),
        _fact(_AMEND2, "us-gaap:NetIncomeLoss", 130.0),
    ]
    assert supersede_facts(facts, lineages) == (facts[2],)


def test_supersede_facts_ungrouped_and_within_filing_duplicates_pass() -> None:
    lineage = _lineage()
    outsider = _fact(_OTHER, "us-gaap:NetIncomeLoss", 5.0)
    dupe_a = _fact(_AMEND, "us-gaap:Assets", 1.0, instant="2023-06-30")
    dupe_b = _fact(_AMEND, "us-gaap:Assets", 2.0, instant="2023-06-30")
    resolved = supersede_facts([outsider, dupe_a, dupe_b], [lineage])
    assert resolved == (outsider, dupe_a, dupe_b)


def test_scope_select_applies_supersession_only_with_lineages() -> None:
    lineage = _lineage()
    facts = [
        _fact(_ORIG, "us-gaap:NetIncomeLoss", 100.0),
        _fact(_AMEND, "us-gaap:NetIncomeLoss", 120.0),
    ]
    pooled = FactScope(start_date="2023-04-01", end_date="2023-06-30")
    assert pooled.select(facts) == tuple(facts)
    resolved = FactScope(
        start_date="2023-04-01", end_date="2023-06-30", lineages=(lineage,)
    )
    assert resolved.select(facts) == (facts[1],)


def test_scope_explicit_accession_reaches_the_original() -> None:
    lineage = _lineage()
    facts = [
        _fact(_ORIG, "us-gaap:NetIncomeLoss", 100.0),
        _fact(_AMEND, "us-gaap:NetIncomeLoss", 120.0),
    ]
    scope = FactScope(accession=_ORIG, lineages=(lineage,))
    assert scope.select(facts) == (facts[0],)


def test_covering_lineage_requires_one_group_for_all_accessions() -> None:
    lineage = _lineage()
    assert covering_lineage([lineage], [_ORIG, _AMEND]) is lineage
    assert covering_lineage([lineage], [_ORIG]) is lineage
    assert covering_lineage([lineage], [_ORIG, _OTHER]) is None
    assert covering_lineage([], [_ORIG]) is None
