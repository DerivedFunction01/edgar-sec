from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
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
from edgar_sec.foundation.runtime.fixtures import (
    FixturePaths,
    fixture_paths as resolve_fixture_paths,
)
from edgar_sec.infra.broker.sec_broker import SecBroker
from edgar_sec.infra.sec_http.client import SecHttpClient
from edgar_sec.infra.sec_http.rate_limit import RateLimiter
from edgar_sec.pipelines.document_inventory.fixture_store.models import (
    FixtureContribution,
)
from tests.support import FakeSession


@dataclass(frozen=True, slots=True)
class BrokerHarness:
    broker: SecBroker
    session: FakeSession


@pytest.fixture
def broker_for() -> Callable[[dict[str, bytes]], BrokerHarness]:
    def make(content_by_url: dict[str, bytes]) -> BrokerHarness:
        session = FakeSession()
        for url, content in content_by_url.items():
            session.register_bytes(url, content)
        broker = SecBroker(
            socket_path=Path("/tmp/document-inventory-test.sock"),
            http_client=SecHttpClient(
                user_agent="InventoryFixtureTests/1.0 test@example.com",
                rate_limiter=RateLimiter(min_interval_s=1e-9),
                session_factory=lambda: session,
            ),
        )
        return BrokerHarness(broker, session)

    return make


@pytest.fixture
def fixture_paths() -> Callable[[Path], FixturePaths]:
    return lambda root: resolve_fixture_paths(root, "document_inventory", "f")


def observation(accession: str, source_cik: str, source_id: str) -> CohortObservation:
    return CohortObservation(
        cohort_source_id=source_id,
        accession=AccessionNumber.from_any(accession),
        source_cik=Cik.from_raw(source_cik),
        form="10-K",
        filing_date=date(2023, 1, 1),
        report_date=None,
    )


def make_cohort(
    accession: str, source_cik: str, source_id: str, url: str
) -> InventoryCohort:
    return InventoryCohort(
        observations=(observation(accession, source_cik, source_id),),
        accessions=(),
        sources=(),
        work_items=(
            IndexWorkItem(accession=AccessionNumber(accession), index_url=url),
        ),
    )


def contribution(
    cohort: InventoryCohort, plan_id: str = "test-plan"
) -> FixtureContribution:
    fingerprint = sha256_text(f"{plan_id}:{len(cohort.work_items)}")
    return FixtureContribution(
        plan_id=plan_id,
        catalog_id="test-catalog",
        scope="10-K",
        plan_schema_version="1",
        request_fingerprint=fingerprint,
        accession_count=len(cohort.work_items),
    )
