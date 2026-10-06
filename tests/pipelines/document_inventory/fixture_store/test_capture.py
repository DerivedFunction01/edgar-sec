from __future__ import annotations

import sqlite3
from pathlib import Path

from edgar_sec.pipelines.document_inventory.fixture_store.capture import (
    capture_index_pages,
    create_index_fixture,
)
from edgar_sec.pipelines.document_inventory.fixture_store.models import (
    FixtureContribution,
)
from edgar_sec.pipelines.document_inventory.fixture_store.reader import list_fixture

from .conftest import contribution, fixture_paths, make_cohort


def test_capture_writes_response_case_and_membership(
    tmp_path: Path, fixture_paths, broker_for
) -> None:
    accession = "0000123456-12-000001"
    url = "https://www.sec.gov/Archives/edgar/data/123456/index.html"
    cohort = make_cohort(accession, "123456789", "source-a", url)
    paths = fixture_paths(tmp_path / "fixture")
    create_index_fixture(paths, fixture_id="f")
    broker = broker_for({url: b"<html>page</html>"})

    result = capture_index_pages(
        cohort,
        fixture_id="f",
        paths=paths,
        broker=broker.broker,
        contribution=contribution(cohort),
    )

    assert result.responses_added == result.cases_created == result.members_created == 1
    assert result.responses_processed == 1
    assert not result.failures
    assert broker.session.calls == [url]
    status = list_fixture(paths)
    assert (status.page_count, status.accession_count, status.membership_count) == (
        1,
        1,
        1,
    )
    assert status.state == "complete"


def test_fill_reuses_page_and_adds_overlapping_provenance(
    tmp_path: Path, fixture_paths, broker_for
) -> None:
    accession = "0000123456-12-000001"
    url = "https://www.sec.gov/Archives/edgar/data/123456/index.html"
    paths = fixture_paths(tmp_path / "fixture")
    create_index_fixture(paths, fixture_id="f")
    first = make_cohort(accession, "111111111", "source-a", url)
    initial = broker_for({url: b"page"})
    capture_index_pages(
        first,
        fixture_id="f",
        paths=paths,
        broker=initial.broker,
        contribution=contribution(first, "plan-a"),
    )
    overlapping = make_cohort(accession, "222222222", "source-b", url)
    unused = broker_for({})

    result = capture_index_pages(
        overlapping,
        fixture_id="f",
        paths=paths,
        broker=unused.broker,
        contribution=contribution(overlapping, "plan-b"),
    )

    assert unused.session.calls == []
    assert result.responses_reused == 1
    assert result.cases_created == result.members_created == 1
    with sqlite3.connect(paths.storage_path) as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM index_responses").fetchone()[0]
            == 1
        )
        assert (
            connection.execute("SELECT COUNT(*) FROM cohort_members").fetchone()[0] == 2
        )
        assert (
            connection.execute(
                "SELECT COUNT(DISTINCT source_cik) FROM cohort_members"
            ).fetchone()[0]
            == 2
        )


def test_partial_capture_is_durable_and_retryable(
    tmp_path: Path, fixture_paths, broker_for
) -> None:
    accessions = ("0000123456-12-000001", "0000123456-12-000002")
    urls = tuple(f"https://www.sec.gov/index/{number}" for number in (1, 2))
    observations = tuple(
        make_cohort(accession, f"{i:010d}", "source", url).observations[0]
        for i, (accession, url) in enumerate(zip(accessions, urls, strict=True), 1)
    )
    from edgar_sec.domain.document_inventory.models import (
        IndexWorkItem,
        InventoryCohort,
    )
    from edgar_sec.domain.identity import AccessionNumber

    cohort = InventoryCohort(
        observations=observations,
        accessions=(),
        sources=(),
        work_items=tuple(
            IndexWorkItem(AccessionNumber(accession), url)
            for accession, url in zip(accessions, urls, strict=True)
        ),
    )
    paths = fixture_paths(tmp_path / "fixture")
    create_index_fixture(paths, fixture_id="f")
    partial = broker_for({urls[0]: b"page"})
    first = capture_index_pages(
        cohort,
        fixture_id="f",
        paths=paths,
        broker=partial.broker,
        contribution=contribution(cohort),
    )
    assert len(first.failures) == 1
    assert list_fixture(paths).state == "partial"
    retry = broker_for({urls[1]: b"recovered"})
    second = capture_index_pages(
        cohort,
        fixture_id="f",
        paths=paths,
        broker=retry.broker,
        contribution=contribution(cohort),
    )
    assert second.responses_reused == 1
    assert second.responses_added == 1
    assert second.failures == ()
    assert retry.session.calls == [urls[1]]
    assert list_fixture(paths).state == "complete"


def test_zero_success_fixture_remains_listable_and_partial(
    tmp_path: Path, fixture_paths, broker_for
) -> None:
    accession = "0000123456-12-000001"
    url = "https://www.sec.gov/index/1"
    cohort = make_cohort(accession, "123456789", "source", url)
    paths = fixture_paths(tmp_path / "fixture")
    create_index_fixture(paths, fixture_id="f")
    result = capture_index_pages(
        cohort,
        fixture_id="f",
        paths=paths,
        broker=broker_for({}).broker,
        contribution=contribution(cohort),
    )
    assert result.responses_added == result.responses_reused == 0
    assert list_fixture(paths).state == "partial"
    assert list_fixture(paths).membership_count == 1
