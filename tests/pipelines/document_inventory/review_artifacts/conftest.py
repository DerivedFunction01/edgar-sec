from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from edgar_sec.domain.document_inventory.models import (
    CohortObservation,
    IndexWorkItem,
    InventoryCohort,
)
from edgar_sec.domain.identity import AccessionNumber, Cik
from edgar_sec.foundation.hashing import sha256_text
from edgar_sec.infra.broker.sec_broker import SecBroker
from edgar_sec.pipelines.document_inventory.fixture_store.capture import (
    capture_index_pages,
    create_index_fixture,
)
from edgar_sec.pipelines.document_inventory.fixture_store.models import (
    FixtureContribution,
)
from edgar_sec.pipelines.document_inventory.paths import inventory_paths
from tests.support import FakeSession, build_test_http, fixture_path


@pytest.fixture
def captured_fixture(tmp_path: Path):
    accession = AccessionNumber("0000200406-26-000001")
    url = (
        "https://www.sec.gov/Archives/edgar/data/200406/000020040626000001/"
        "0000200406-26-000001-index.html"
    )
    body = fixture_path("document_inventory_index_page.html").read_bytes()
    observation = CohortObservation(
        "catalog-plan:test",
        accession,
        Cik.from_raw("0000200406"),
        "10-K",
        date(2026, 1, 1),
        None,
    )
    cohort = InventoryCohort(
        observations=(observation,),
        accessions=(),
        sources=(),
        work_items=(IndexWorkItem(accession, url),),
    )
    contribution = FixtureContribution(
        plan_id="test-plan",
        catalog_id="test-catalog",
        scope="10-K",
        plan_schema_version="1",
        request_fingerprint=sha256_text("test-plan:1"),
        accession_count=1,
    )
    paths = inventory_paths(tmp_path).index_fixture_paths("fixture")
    create_index_fixture(paths, fixture_id="fixture")
    session = FakeSession()
    session.register_bytes(url, body)
    broker = SecBroker(
        socket_path=tmp_path / "fixture.sock",
        http_client=build_test_http(session),
    )
    capture_index_pages(
        cohort,
        fixture_id="fixture",
        paths=paths,
        broker=broker,
        contribution=contribution,
    )
    return paths, accession, body


@pytest.fixture
def captured_multi_fixture(tmp_path: Path):
    accessions = (
        AccessionNumber("0000200406-26-000001"),
        AccessionNumber("0000200406-26-000002"),
    )
    urls = tuple(
        f"https://www.sec.gov/Archives/edgar/data/200406/{item.normalized}/{item}-index.html"
        for item in accessions
    )
    bodies = (
        fixture_path("document_inventory_index_page.html").read_bytes(),
        b"<html><body>not a filing index</body></html>",
    )
    observations = tuple(
        CohortObservation(
            "catalog-plan:test",
            accession,
            Cik.from_raw("0000200406"),
            "10-K",
            date(2026, 1, 1),
            None,
        )
        for accession in accessions
    )
    cohort = InventoryCohort(
        observations=observations,
        accessions=(),
        sources=(),
        work_items=tuple(
            IndexWorkItem(accession, url)
            for accession, url in zip(accessions, urls, strict=True)
        ),
    )
    contribution = FixtureContribution(
        "test-plan",
        "test-catalog",
        "10-K",
        "1",
        sha256_text("test-plan:2"),
        2,
    )
    paths = inventory_paths(tmp_path).index_fixture_paths("fixture")
    create_index_fixture(paths, fixture_id="fixture")
    session = FakeSession()
    for url, body in zip(urls, bodies, strict=True):
        session.register_bytes(url, body)
    broker = SecBroker(
        socket_path=tmp_path / "fixture.sock",
        http_client=build_test_http(session),
    )
    capture_index_pages(
        cohort,
        fixture_id="fixture",
        paths=paths,
        broker=broker,
        contribution=contribution,
    )
    return paths, accessions
