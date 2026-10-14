"""Unit tests verifying fact cube coordinate normalization and dimensional categorization."""

from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.engine.xbrl.schema.models import XbrlFact
from edgar_sec.engine.xbrl.normalize.normalization import (
    classify_axis_family,
    classify_member_role,
    normalize_dimension_slices,
    normalize_fact,
    normalize_time_coordinate,
    normalize_unit_class,
)


def test_normalize_time_coordinate_instant_and_durations() -> None:
    """Verify time kind and length classification across instant and duration spans."""
    t_inst = normalize_time_coordinate("instant", "2024-09-30", None, None)
    assert t_inst.kind == "INSTANT"
    assert t_inst.length_class == "INSTANT"
    assert t_inst.date == "2024-09-30"

    t_ann = normalize_time_coordinate("duration", None, "2023-10-01", "2024-09-30")
    assert t_ann.kind == "DURATION"
    assert t_ann.length_class == "ANNUAL"
    assert t_ann.days == 365

    t_qtr = normalize_time_coordinate("duration", None, "2024-07-01", "2024-09-30")
    assert t_qtr.kind == "DURATION"
    assert t_qtr.length_class == "QUARTER"
    assert t_qtr.days == 91

    t_ytd = normalize_time_coordinate("duration", None, "2024-01-01", "2024-06-30")
    assert t_ytd.length_class == "YTD_2Q"


def test_classify_axis_family() -> None:
    """Verify semantic classification of dimension axis QNames."""
    assert classify_axis_family("us-gaap:StatementGeographicalAxis") == "GEOGRAPHY"
    assert classify_axis_family("us-gaap:StatementBusinessSegmentsAxis") == "SEGMENT"
    assert classify_axis_family("us-gaap:ProductOrServiceAxis") == "PRODUCT_SERVICE"
    assert classify_axis_family("us-gaap:MajorCustomersAxis") == "CUSTOMER"
    assert classify_axis_family("us-gaap:DebtInstrumentAxis") == "INSTRUMENT"
    assert classify_axis_family("custom:ArbitraryAxis") == "OTHER"


def test_classify_member_role() -> None:
    """Verify member aggregation role classification."""
    assert classify_member_role("us-gaap:GeographicalDomain") == "DEFAULT"
    assert classify_member_role("us-gaap:TotalMember") == "TOTAL"
    assert classify_member_role("us-gaap:CorporateNonSegmentMember") == "RECONCILING"
    assert classify_member_role("us-gaap:NorthAmericaMember") == "NORMAL"


def test_normalize_unit_class() -> None:
    """Verify standard unit string normalization."""
    assert normalize_unit_class("iso4217:USD") == "USD"
    assert normalize_unit_class("USD") == "USD"
    assert normalize_unit_class("$") == "USD"
    assert normalize_unit_class("shares") == "SHARES"
    assert normalize_unit_class("pure") == "PURE"
    assert normalize_unit_class(None) == "PURE"


def test_normalize_fact_cube_projection() -> None:
    """Verify complete fact normalization into fact cube coordinates."""
    acc = AccessionNumber("0000950170-24-087843")
    fact = XbrlFact(
        accession=acc,
        concept_qname="us-gaap:Revenues",
        value="1250000.5",
        unit="USD",
        period_type="duration",
        start_date="2023-10-01",
        end_date="2024-09-30",
        dimensions={
            "us-gaap:StatementGeographicalAxis": "us-gaap:NorthAmericaMember",
            "us-gaap:StatementBusinessSegmentsAxis": "us-gaap:OperatingSegmentsDomain",
        },
    )

    norm = normalize_fact(fact)
    assert norm.canonical_value == 1250000.5
    assert norm.unit_class == "USD"
    assert norm.time.length_class == "ANNUAL"
    assert len(norm.dimensions) == 2
    assert norm.dimensions[0].axis_family == "SEGMENT"
    assert norm.dimensions[0].member_role == "DEFAULT"
    assert norm.dimensions[1].axis_family == "GEOGRAPHY"
    assert norm.dimensions[1].member_role == "NORMAL"
