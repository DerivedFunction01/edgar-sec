"""Stitched-value model: exact period identity and provenance carriage."""

from __future__ import annotations

import pytest

from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.engine.xbrl.schema.models import XbrlFact
from edgar_sec.engine.xbrl.solve.query import QueryStatus
from edgar_sec.engine.xbrl.solve.stitched import (
    DERIVED_EXACT_BASIS,
    DerivationInput,
    StitchedValue,
)

_ORIGINAL = "0000000001-24-000001"
_AMENDMENT = "0000000001-24-000002"
_CONCEPT = "us-gaap:Revenues"


def _fact(
    value: float = 100.0,
    *,
    accession: str = _ORIGINAL,
    start: str = "2024-01-01",
    end: str = "2024-03-31",
    period_type: str = "duration",
    instant: str | None = None,
    dimensions: dict[str, str] | None = None,
) -> XbrlFact:
    return XbrlFact(
        accession=AccessionNumber.from_any(accession),
        concept_qname=_CONCEPT,
        value=value,
        unit="USD",
        period_type=period_type,
        start_date=start if period_type == "duration" else None,
        end_date=end if period_type == "duration" else None,
        instant_date=instant,
        dimensions=dimensions or {},
    )


def test_from_fact_carries_exact_period_and_provenance() -> None:
    value = StitchedValue.from_fact(_fact())
    assert value.key == (
        _CONCEPT,
        "duration",
        "2024-01-01",
        "2024-03-31",
        None,
        "USD",
        (),
    )
    assert value.status == QueryStatus.REPORTED
    assert value.source_accession == _ORIGINAL
    assert value.value == 100.0
    assert not value.is_superseded


def test_key_distinguishes_quarter_from_ytd_ending_the_same_day() -> None:
    quarter = StitchedValue.from_fact(_fact(start="2024-01-01", end="2024-03-31"))
    ytd = StitchedValue.from_fact(_fact(start="2023-10-01", end="2024-03-31"))
    assert quarter.period_key != ytd.period_key
    assert quarter.key != ytd.key


def test_key_distinguishes_dimensions_and_units() -> None:
    plain = StitchedValue.from_fact(_fact())
    segmented = StitchedValue.from_fact(_fact(dimensions={"axis": "member"}))
    assert plain.key != segmented.key


def test_instant_value_keys_on_the_instant() -> None:
    value = StitchedValue.from_fact(_fact(period_type="instant", instant="2024-03-31"))
    assert value.period_key == ("instant", None, None, "2024-03-31")


def test_period_shape_is_validated() -> None:
    with pytest.raises(ValueError):
        StitchedValue(
            concept_qname=_CONCEPT,
            period_type="duration",
            unit="USD",
            value=1.0,
            status=QueryStatus.REPORTED,
            source_accession=_ORIGINAL,
            instant_date="2024-03-31",
        )
    with pytest.raises(ValueError):
        StitchedValue(
            concept_qname=_CONCEPT,
            period_type="instant",
            unit="USD",
            value=1.0,
            status=QueryStatus.REPORTED,
            source_accession=_ORIGINAL,
            start_date="2024-01-01",
            end_date="2024-03-31",
        )


def test_derived_value_must_name_its_inputs() -> None:
    with pytest.raises(ValueError):
        StitchedValue(
            concept_qname=_CONCEPT,
            period_type="duration",
            unit="USD",
            value=30.0,
            status=QueryStatus.DERIVED,
            source_accession=_ORIGINAL,
            start_date="2024-01-01",
            end_date="2024-03-31",
            basis=DERIVED_EXACT_BASIS,
        )


def test_derived_value_round_trips_with_inputs_named() -> None:
    legs = (
        DerivationInput.from_fact(_fact(250.0, end="2024-06-30", start="2024-01-01")),
        DerivationInput.from_fact(_fact(100.0)),
    )
    value = StitchedValue(
        concept_qname=_CONCEPT,
        period_type="duration",
        unit="USD",
        value=150.0,
        status=QueryStatus.DERIVED,
        source_accession=_ORIGINAL,
        start_date="2024-04-01",
        end_date="2024-06-30",
        basis=DERIVED_EXACT_BASIS,
        derivation_path=("ytd_difference",),
        derivation_inputs=legs,
    )
    assert StitchedValue.from_dict(value.to_dict()) == value


def test_superseded_copy_retains_the_losing_value_and_names_the_winner() -> None:
    value = StitchedValue.from_fact(_fact(100.0))
    marked = value.superseded(_AMENDMENT)
    assert marked.is_superseded
    assert marked.value == 100.0
    assert marked.source_accession == _ORIGINAL
    assert marked.superseded_by == _AMENDMENT
    assert StitchedValue.from_dict(marked.to_dict()) == marked
    with pytest.raises(ValueError):
        value.superseded(_ORIGINAL)


def test_reported_value_round_trips() -> None:
    value = StitchedValue.from_fact(_fact(dimensions={"axis": "member"}))
    assert StitchedValue.from_dict(value.to_dict()) == value


def test_from_fact_rejects_non_numeric_facts() -> None:
    fact = XbrlFact(
        accession=AccessionNumber.from_any(_ORIGINAL),
        concept_qname="dei:DocumentType",
        value="10-Q",
        period_type="duration",
        start_date="2024-01-01",
        end_date="2024-03-31",
    )
    with pytest.raises(ValueError):
        StitchedValue.from_fact(fact)
