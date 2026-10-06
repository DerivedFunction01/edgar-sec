"""Append-only capture-and-replay store for index pages.

All tests are offline: a fake broker serves pre-baked index-page bytes and no
network is ever contacted. One test file per module under pipelines.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from edgar_sec.domain.identity import AccessionNumber, Cik
from edgar_sec.foundation.hashing import sha256_bytes
from edgar_sec.foundation.compression import decompress_payload
from edgar_sec.infra.broker.sec_broker import SecBroker
from edgar_sec.infra.sec_http.client import SecHttpClient
from edgar_sec.infra.sec_http.errors import PermanentHttpError
from edgar_sec.infra.sec_http.rate_limit import RateLimiter
from edgar_sec.pipelines.document_inventory.cohort import (
    CohortObservation,
    InventoryCohort,
    IndexWorkItem,
    index_url_for,
    project_cohort,
    read_catalog_observations,
)
from edgar_sec.pipelines.document_inventory.fixture_store import (
    CapturedIndexPage,
    IndexCaptureFailure,
    IndexCaptureResult,
    IndexFixtureError,
    IndexFixturePaths,
    IndexResponseKey,
    capture_index_pages,
    create_index_fixture,
    list_index_cases,
    publish_index_fixture,
    replay_index_page,
    SCHEMA_VERSION,
)
from tests.support import FakeSession, fixture_path


def _fake_http_client(content_by_url: dict[str, bytes]) -> SecHttpClient:
    session = FakeSession()
    for url, content in content_by_url.items():
        session.register_bytes(url, content)
    return SecHttpClient(
        user_agent="FixtureStoreTest/1.0 test@example.com",
        rate_limiter=RateLimiter(min_interval_s=1e-9),
        session_factory=lambda: session,
    )


def _broker_for(
    content_by_url: dict[str, bytes], socket_path: Path | None = None
) -> SecBroker:
    return SecBroker(
        socket_path=(socket_path or Path("/tmp/fixture-broker.sock")),
        http_client=_fake_http_client(content_by_url),
    )


def _capture_and_publish(
    tmp_path: Path, cohort: InventoryCohort, broker: SecBroker
) -> IndexFixturePaths:
    fixture_path_obj = tmp_path / "fixture"
    create_index_fixture(fixture_path_obj, fixture_id="t")
    capture_index_pages(cohort, fixture_id="t", paths=fixture_path_obj, broker=broker)
    return fixture_path_obj


def _obs(accession: str, source_cik: str, source_id: str) -> CohortObservation:
    return CohortObservation(
        cohort_source_id=source_id,
        accession=AccessionNumber.from_any(accession),
        source_cik=Cik.from_raw(source_cik),
        form="10-K",
        filing_date=date(2023, 1, 1),
        report_date=None,
    )


def _cohort(
    accession: str, source_cik: str, source_id: str, url: str
) -> InventoryCohort:
    return InventoryCohort(
        observations=(_obs(accession, source_cik, source_id),),
        accessions=(),
        sources=(),
        work_items=(
            IndexWorkItem(accession=AccessionNumber.from_any(accession), index_url=url),
        ),
    )


def test_url_digest_dedup(tmp_path: Path) -> None:
    """Same page fetched twice: one row added, the second fetch is reused."""
    url = "https://www.sec.gov/Archives/edgar/data/1234567890/000012345612000001/-index.html"
    content = b"<html>index</html>"
    cohort = _cohort("0000123456-12-000001", "123456789", "src", url)
    fixture_root = tmp_path / "fixture"
    create_index_fixture(fixture_root, fixture_id="t")
    r1 = capture_index_pages(
        cohort, fixture_id="t", paths=fixture_root, broker=_broker_for({url: content})
    )
    assert r1.responses_added == 1 and r1.responses_reused == 0
    r2 = capture_index_pages(
        cohort, fixture_id="t", paths=fixture_root, broker=_broker_for({url: content})
    )
    assert r2.responses_added == 0 and r2.responses_reused == 1
    assert r1.cases_created == 1 and r2.cases_created == 0
    manifest = publish_index_fixture(fixture_root)
    assert manifest.page_count == 1 and manifest.accession_count == 1


def test_changed_response_appends(tmp_path: Path) -> None:
    """Changed response bytes produce a new row; the old row persists."""
    url = "https://www.sec.gov/Archives/edgar/data/1234567890/000012345612000001/-index.html"
    content1 = b"<html>old</html>"
    content2 = b"<html>new</html>"
    cohort = _cohort("0000123456-12-000001", "123456789", "src", url)
    fixture_root = _capture_and_publish(tmp_path, cohort, _broker_for({url: content1}))
    r2 = capture_index_pages(
        cohort, fixture_id="t", paths=fixture_root, broker=_broker_for({url: content2})
    )
    assert r2.responses_added == 1 and r2.responses_reused == 0
    manifest = publish_index_fixture(fixture_root)
    assert manifest.page_count == 2
    conn = sqlite3.connect(str(fixture_root / "index_fixtures.sqlite"))
    rows = conn.execute(
        "SELECT response_sha256 FROM index_responses ORDER BY byte_size"
    ).fetchall()
    assert len(rows) == 2
    old_hash = sha256_bytes(content1)
    new_hash = sha256_bytes(content2)
    old_keys = [
        k
        for k in list_index_cases(fixture_root, AccessionNumber("0000123456-12-000001"))
        if k.response_sha256 == old_hash
    ]
    page = replay_index_page(
        fixture_root, AccessionNumber("0000123456-12-000001"), old_keys[0]
    )
    assert page.byte_size == len(content1)
    assert str(page.request_url) == url


def test_source_cik_union(tmp_path: Path) -> None:
    """Two cohort sources contribute one page: one page row, multiple cohort_members."""
    url = "https://www.sec.gov/Archives/edgar/data/1234567890/000012345612000001/-index.html"
    content = b"<html>shared page</html>"
    cohort = InventoryCohort(
        observations=(
            _obs("0000123456-12-000001", "123456789", "srcA"),
            _obs("0000123456-12-000001", "987654321", "srcB"),
        ),
        accessions=(),
        sources=(),
        work_items=(
            IndexWorkItem(
                accession=AccessionNumber("0000123456-12-000001"), index_url=url
            ),
        ),
    )
    fixture_root = tmp_path / "fixture"
    create_index_fixture(fixture_root, fixture_id="t")
    r = capture_index_pages(
        cohort, fixture_id="t", paths=fixture_root, broker=_broker_for({url: content})
    )
    assert r.responses_added == 1 and r.responses_reused == 0
    assert r.cases_created == 2 and r.accessions_seen == 2
    manifest = publish_index_fixture(fixture_root)
    assert manifest.page_count == 1 and manifest.accession_count == 2
    conn = sqlite3.connect(str(fixture_root / "index_fixtures.sqlite"))
    members = conn.execute(
        "SELECT accession, source_cik FROM cohort_members ORDER BY accession"
    ).fetchall()
    assert len(members) == 2
    assert manifest.cohort_source_ids == ("srcA", "srcB")


def test_exact_byte_hash_roundtrip(tmp_path: Path) -> None:
    """Replayed page body equals the captured bytes and hashes to the stored digest."""
    url = "https://www.sec.gov/Archives/edgar/data/1234567890/000012345612000001/-index.html"
    content = b"z" * 8192
    cohort = _cohort("0000123456-12-000001", "123456789", "src", url)
    fixture_root = _capture_and_publish(tmp_path, cohort, _broker_for({url: content}))
    manifest = publish_index_fixture(fixture_root)
    keys = list_index_cases(fixture_root, AccessionNumber("0000123456-12-000001"))
    assert len(keys) == 1
    page = replay_index_page(
        fixture_root, AccessionNumber("0000123456-12-000001"), keys[0]
    )
    assert page.byte_size == len(content)
    assert page.response_sha256 == sha256_bytes(content)
    assert str(page.request_url) == url
    assert page.captured_at is not None
    # response_sha256 is the digest of the uncompressed content;
    # compressed_body is the zstd frame on disk, so we decompress first.
    assert str(page.response_sha256) == sha256_bytes(
        decompress_payload(page.compressed_body)
    )


def test_readonly_nonmutation(tmp_path: Path) -> None:
    """A read-only replay database cannot be altered by any SQL."""
    url = "https://www.sec.gov/Archives/edgar/data/1234567890/000012345612000001/-index.html"
    content = b"<html>index</html>"
    cohort = _cohort("0000123456-12-000001", "123456789", "src", url)
    fixture_root = _capture_and_publish(tmp_path, cohort, _broker_for({url: content}))
    publish_index_fixture(fixture_root)
    db = fixture_root / "index_fixtures.sqlite"
    with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as conn:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            conn.execute("DELETE FROM index_responses WHERE rowid = 1")
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            conn.execute("INSERT INTO index_cases VALUES (1,'x','y','z','w')")


def test_wrong_schema_refusal(tmp_path: Path) -> None:
    """Replay refuses a manifest whose schema_version no longer matches the store."""
    url = "https://www.sec.gov/Archives/edgar/data/1234567890/000012345612000001/-index.html"
    content = b"<html>index</html>"
    cohort = _cohort("0000123456-12-000001", "123456789", "src", url)
    fixture_root = _capture_and_publish(tmp_path, cohort, _broker_for({url: content}))
    publish_index_fixture(fixture_root)
    manifest_path = fixture_root / "manifest.json"
    keys = list_index_cases(fixture_root, AccessionNumber("0000123456-12-000001"))
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    data["schema_version"] = 99
    manifest_path.write_text(json.dumps(data, sort_keys=True))
    with pytest.raises(IndexFixtureError, match="schema_version"):
        replay_index_page(
            fixture_root, AccessionNumber("0000123456-12-000001"), keys[0]
        )


def test_atomic_manifest_after_commit(tmp_path: Path) -> None:
    """After publish the manifest database_sha256 equals the SHA-256 of the committed file."""
    url = "https://www.sec.gov/Archives/edgar/data/1234567890/000012345612000001/-index.html"
    content = b"<html>index</html>"
    cohort = _cohort("0000123456-12-000001", "123456789", "src", url)
    fixture_root = _capture_and_publish(tmp_path, cohort, _broker_for({url: content}))
    manifest = publish_index_fixture(fixture_root)
    db_digest = sha256_bytes((fixture_root / "index_fixtures.sqlite").read_bytes())
    assert manifest.database_sha256 == db_digest
    assert manifest.page_count == 1 and manifest.accession_count == 1
    assert manifest.database_path == "index_fixtures.sqlite"


def test_replay_without_http(tmp_path: Path) -> None:
    """Replay resolves cases solely from the fixture store; no broker is involved."""
    url = "https://www.sec.gov/Archives/edgar/data/1234567890/000012345612000001/-index.html"
    content = b"<html>index</html>"
    cohort = _cohort("0000123456-12-000001", "123456789", "src", url)
    fixture_root = _capture_and_publish(tmp_path, cohort, _broker_for({url: content}))
    manifest = publish_index_fixture(fixture_root)
    assert manifest.database_sha256 is not None
    keys = list_index_cases(fixture_root, AccessionNumber("0000123456-12-000001"))
    assert len(keys) == 1
    page = replay_index_page(
        fixture_root, AccessionNumber("0000123456-12-000001"), keys[0]
    )
    assert len(page.request_url) > 0 and len(page.compressed_body) > 0


def test_deterministic_case_ordering(tmp_path: Path) -> None:
    """list_index_cases returns stable sorted order regardless of insert order."""
    urls: dict[str, str] = {}
    contents: dict[str, bytes] = {}
    observations: list[CohortObservation] = []
    work_items: list[IndexWorkItem] = []
    for i in range(5):
        acc = AccessionNumber.from_any(f"{1_000_000 + i:010d}-12-000001")
        url = f"https://www.sec.gov/Archives/edgar/data/{1_000_000 + i}/{'0' * 18}/-index.html"
        urls[str(acc)] = url
        contents[url] = f"content-{i}".encode()
        work_items.append(IndexWorkItem(accession=acc, index_url=url))
        observations.append(_obs(str(acc), f"{1_000_000 + i}", "src"))
    cohort = InventoryCohort(
        observations=tuple(observations),
        accessions=(),
        sources=(),
        work_items=tuple(reversed(work_items)),
    )
    fixture_root = _capture_and_publish(tmp_path, cohort, _broker_for(contents))
    manifest = publish_index_fixture(fixture_root)
    assert manifest.page_count == 5 and manifest.accession_count == 5
    for i in range(5):
        acc = AccessionNumber.from_any(f"{1_000_000 + i:010d}-12-000001")
        keys = list_index_cases(fixture_root, acc)
        assert keys == tuple(
            sorted(keys, key=lambda k: (k.request_url, k.response_sha256))
        )


def test_capture_failure_writes_cohort_member_not_page(tmp_path: Path) -> None:
    """A transport failure maps to a stable code, writes no page/case, keeps the member."""
    url = "https://www.sec.gov/Archives/edgar/data/1234567890/000012345612000001/-index.html"
    acc = "0000123456-12-000001"
    content = b"<html>ok</html>"
    cohort_ok = _cohort(acc, "123456789", "src", url)
    fixture_root = _capture_and_publish(
        tmp_path, cohort_ok, _broker_for({url: content})
    )
    pages_before = (
        sqlite3.connect(str(fixture_root / "index_fixtures.sqlite"))
        .execute("SELECT COUNT(*) FROM index_responses")
        .fetchone()[0]
    )
    cases_before = (
        sqlite3.connect(str(fixture_root / "index_fixtures.sqlite"))
        .execute("SELECT COUNT(*) FROM index_cases")
        .fetchone()[0]
    )

    class _FailingSession(FakeSession):
        def get(self, url, headers=None, timeout=None):
            raise PermanentHttpError(url, "404 not found", 404)

    session = _FailingSession()
    broker_fail = SecBroker(
        socket_path=tmp_path / "broker.sock",
        http_client=SecHttpClient(
            user_agent="X/1.0 x@example.com",
            rate_limiter=RateLimiter(min_interval_s=1e-9),
            session_factory=lambda: session,
        ),
    )
    obs_fail = _obs(acc, "123456789", "src")
    cohort_fail = InventoryCohort(
        observations=(obs_fail,),
        accessions=(),
        sources=(),
        work_items=(IndexWorkItem(accession=AccessionNumber(acc), index_url=url),),
    )
    r = capture_index_pages(
        cohort_fail, fixture_id="t", paths=fixture_root, broker=broker_fail
    )
    assert len(r.failures) == 1
    assert r.failures[0].accession == AccessionNumber(acc)
    assert r.failures[0].failure_code == "permanent_http_error"
    assert (
        r.failures[0].raw_broker_error is not None
        and "404" in r.failures[0].raw_broker_error
    )
    assert r.responses_added == 0 and r.responses_reused == 0 and r.cases_created == 0
    conn = sqlite3.connect(str(fixture_root / "index_fixtures.sqlite"))
    pages_after = conn.execute("SELECT COUNT(*) FROM index_responses").fetchone()[0]
    cases_after = conn.execute("SELECT COUNT(*) FROM index_cases").fetchone()[0]
    failure_members = conn.execute(
        "SELECT * FROM cohort_members WHERE failure_code IS NOT NULL"
    ).fetchall()
    assert pages_after == pages_before
    assert cases_after == cases_before
    assert len(failure_members) == 1


def test_index_page_for_18_digit_accession(tmp_path: Path) -> None:
    """The 18-digit accession edge case yields a URL with a bare (unpadded) archive CIK."""
    accession = AccessionNumber.from_any("000000901500000054")
    url = index_url_for(
        accession, archive_base_url="https://www.sec.gov/Archives/edgar/data"
    )
    assert (
        url
        == "https://www.sec.gov/Archives/edgar/data/9015/000000901500000054/-index.html"
    )
    content = b"<html>index</html>"
    cohort = InventoryCohort(
        observations=(_obs(str(accession), "0000000020", "s1"),),
        accessions=(),
        sources=(),
        work_items=(IndexWorkItem(accession=accession, index_url=url),),
    )
    fixture_root = _capture_and_publish(tmp_path, cohort, _broker_for({url: content}))
    manifest = publish_index_fixture(fixture_root)
    keys = list_index_cases(fixture_root, accession)
    assert len(keys) == 1
    page = replay_index_page(fixture_root, accession, keys[0])
    assert page.response_sha256 == sha256_bytes(content)


def test_capture_real_s1_cohort(tmp_path: Path) -> None:
    """Capture a small real cohort from the committed S1 fixtures against the fake broker."""
    plan_dir = fixture_path("catalog/s1_plan")
    observations = list(
        read_catalog_observations(plan_dir, "s1-cohort-plan", "catalog_plan")
    )
    inventory = project_cohort(
        observations, archive_base_url="https://www.sec.gov/Archives/edgar/data"
    )
    content_by_url: dict[str, bytes] = {}
    for wi in inventory.work_items:
        content_by_url[wi.index_url] = (
            b"SEC index page bytes for " + wi.index_url.encode()
        )
    broker = _broker_for(content_by_url, socket_path=tmp_path / "broker.sock")
    fixture_root = _capture_and_publish(tmp_path, inventory, broker)
    manifest = publish_index_fixture(fixture_root)
    assert manifest.page_count == len(inventory.work_items)
    assert manifest.accession_count == len(inventory.work_items)
    assert manifest.cohort_source_ids
    assert manifest.database_sha256 is not None
    for wi in inventory.work_items:
        keys = list_index_cases(fixture_root, wi.accession)
        assert len(keys) == 1
        page = replay_index_page(fixture_root, wi.accession, keys[0])
        assert page.response_sha256 == sha256_bytes(content_by_url[wi.index_url])


def test_create_refuses_unrelated_database(tmp_path: Path) -> None:
    """create_index_fixture refuses a pre-existing unrelated SQLite database."""
    fixture_root = tmp_path / "fixture"
    unrelated = fixture_root / "index_fixtures.sqlite"
    unrelated.parent.mkdir(parents=True, exist_ok=True)
    sqlite3.connect(str(unrelated)).execute("CREATE TABLE unrelated (value TEXT)")
    with pytest.raises(IndexFixtureError, match="not an index fixture store"):
        create_index_fixture(fixture_root, fixture_id="x")
