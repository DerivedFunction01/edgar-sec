"""Deferred domain models: nothing in the current pipeline constructs them, and
this pins that so the deferred status stays honest.
"""

from __future__ import annotations

import dataclasses

import pytest

from edgar_sec.domain.identity import Cik
from edgar_sec.domain.submissions import models
from edgar_sec.domain.submissions.models import (
    Address,
    EntityProfile,
    FilingRecord,
    FormerName,
    Listing,
    SubmissionsAggregate,
)

MODEL_NAMES = (
    "Address",
    "EntityProfile",
    "FilingRecord",
    "FormerName",
    "Listing",
    "SubmissionsAggregate",
)


def test_every_model_is_exported_and_is_a_frozen_dataclass() -> None:
    assert set(models.__all__) == set(MODEL_NAMES)
    for name in MODEL_NAMES:
        model = getattr(models, name)
        assert dataclasses.is_dataclass(model), name
        assert model.__dataclass_params__.frozen, name


def test_models_default_construct_without_arguments_except_required() -> None:
    assert Address() == Address(None, None, None, None, None, None, None, None, None)
    assert FormerName(name="ACME").to_date is None
    assert Listing("AAPL", "NASDAQ").exchange == "NASDAQ"
    assert FilingRecord().items == ()
    assert EntityProfile(cik=Cik(1985), name="ACME").former_names == ()
    assert EntityProfile(cik=Cik(1985), name="ACME").mailing_address is None


def test_entity_profile_keeps_cik_identity() -> None:
    profile = EntityProfile(cik=Cik(37996), name="FORD MOTOR CO")
    assert profile.cik == Cik(37996)
    assert str(profile.cik.to_10digit()) == "0000037996"
    assert profile.cik is Cik(37996) or profile.cik == Cik(37996)


def test_nested_value_objects_compose_into_a_profile() -> None:
    profile = EntityProfile(
        cik=Cik(1985),
        name="ACCEL INTERNATIONAL CORP",
        former_names=(FormerName(name="OLD NAME", from_date="2010-01-01"),),
        listings=(Listing(ticker="A", exchange="NYSE"),),
        mailing_address=Address(city="NEW YORK", state_or_country="NY"),
    )
    assert profile.former_names[0].name == "OLD NAME"
    assert profile.listings[0].ticker == "A"
    assert profile.mailing_address is not None
    assert profile.mailing_address.city == "NEW YORK"


def test_filing_record_tracks_its_source_provenance() -> None:
    record = FilingRecord(
        accession_number="0000037996-26-000001",
        source_section="filings.recent",
        source_file="CIK0000037996.json",
        source_array_index=3,
    )
    assert record.source_section == "filings.recent"
    assert record.source_array_index == 3
    assert record.primary_document is None


def test_aggregate_binds_a_profile_to_its_filings_and_anomalies() -> None:
    cik = Cik(1985)
    aggregate = SubmissionsAggregate(
        cik=cik,
        profile=EntityProfile(cik=cik, name="ACCEL"),
        filings=(FilingRecord(accession_number="0000001985-26-000001"),),
        anomalies=({"code": "alias_conflict", "detail": "x", "source": "y"},),
    )
    assert aggregate.cik == cik
    assert aggregate.profile.cik == cik
    assert len(aggregate.filings) == 1
    assert aggregate.anomalies[0]["code"] == "alias_conflict"
    assert aggregate.extra_fields is None


def test_models_are_immutable() -> None:
    profile = EntityProfile(cik=Cik(1985), name="ACME")
    with pytest.raises(dataclasses.FrozenInstanceError):
        profile.name = "OTHER"  # type: ignore[misc]


def test_no_current_pipeline_constructs_these_models() -> None:
    """An adapter that starts producing these must replace this test."""
    from pathlib import Path

    from edgar_sec.engine.submissions import builder, filings, profile
    from edgar_sec.pipelines.metadata_sync import worker

    for module in (builder, filings, profile, worker):
        source = Path(str(module.__file__)).read_text(encoding="utf-8")
        for name in MODEL_NAMES:
            assert f"{name}(" not in source, f"{module.__name__} constructs {name}"
