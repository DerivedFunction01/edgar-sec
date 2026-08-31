"""Tests for offline fixture builder utility."""

from __future__ import annotations

import importlib
import json
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path

import pytest

from defs.runtime.paths import resolve_paths
from defs.sql import Select, SqlDialect, Table, col, make_sql_executor

fixture_builder = importlib.import_module(
    "phases.025_webpage_storage.core.fixture_builder"
)
schemas = importlib.import_module("phases.025_webpage_storage.core.schemas")
cli = importlib.import_module("phases.025_webpage_storage.cli")


@dataclass
class FakeHttpClient:
    payloads: dict[str, bytes]

    def get_bytes(self, url: str) -> bytes:
        if url in self.payloads:
            return self.payloads[url]
        raise ValueError(f"404 Not Found: {url}")


class BarrierHttpClient:
    """Fake client that synchronizes concurrent fetches on a barrier.

    Proves that multiple fixture fetch threads run concurrently: every
    outstanding ``get_bytes`` call increments ``active`` before blocking on
    the barrier, so ``max_active`` records the true concurrency.
    """

    def __init__(self, payloads: dict[str, bytes], num_workers: int):
        self.payloads = payloads
        self._barrier = threading.Barrier(num_workers, timeout=10)
        self._lock = threading.Lock()
        self.active = 0
        self.max_active = 0
        self.calls: list[str] = []

    def get_bytes(self, url: str) -> bytes:
        with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            self.calls.append(url)
        try:
            self._barrier.wait()
        except threading.BrokenBarrierError:
            pass
        with self._lock:
            self.active -= 1
        if url in self.payloads:
            return self.payloads[url]
        raise ValueError(f"404 Not Found: {url}")


class TrackingHttpClient(FakeHttpClient):
    """Fake client that records every requested URL."""

    def __init__(self, payloads: dict[str, bytes]) -> None:
        super().__init__(payloads)
        self.calls: list[str] = []

    def get_bytes(self, url: str) -> bytes:
        self.calls.append(url)
        return super().get_bytes(url)


def _build_multi_doc_bundle(root: Path, count: int = 5) -> Path:
    """Build a Phase 02 bundle with ``count`` distinct documents."""
    conftest_mod = importlib.import_module("phases.025_webpage_storage.tests.conftest")
    documents: dict[str, bytes] = {}
    occurrences: list[dict] = []
    for i in range(count):
        accession = f"000000000{i + 1:02d}0000000{i + 1}"
        path = f"doc{i}.htm"
        documents[f"{accession}/{path}"] = f"<html>doc{i}</html>".encode()
        occurrences.append(
            {
                "occurrence_id": f"occ-{i}",
                "document_locator_key": f"loc-{i}",
                "source_cik": f"000000000{i + 1}",
                "accession": accession,
                "form": "10-K",
                "filing_date": "2024-01-02",
                "report_date": "2023-12-31",
                "document_path": path,
            }
        )
    return conftest_mod.build_phase02_bundle(
        root, documents=documents, occurrences=occurrences
    )


def _payload_urls(count: int = 5) -> dict[str, bytes]:
    payloads: dict[str, bytes] = {}
    for i in range(count):
        accession = f"000000000{i + 1:02d}0000000{i + 1}"
        path = f"doc{i}.htm"
        payloads[f"https://www.sec.gov/Archives/{accession}/{path}"] = (
            f"<html>doc{i}</html>".encode()
        )
    return payloads


def test_fill_fixture_populates_sqlite_directly(phase02_bundle: Path, tmp_path: Path):
    fixture_id = f"test-fix-{uuid.uuid4().hex[:8]}"
    fake_client = FakeHttpClient(
        {
            "https://www.sec.gov/Archives/000000000100000001/10k.htm": b"<html>doc1</html>",
            "https://www.sec.gov/Archives/000000000100000001/10k2.htm": b"<html>doc2</html>",
        }
    )

    result = fixture_builder.fill_fixture(
        phase02_bundle,
        fixture_id=fixture_id,
        http_client=fake_client,
    )

    assert result["fixture_id"] == fixture_id
    assert result["newly_fetched"] == 2
    assert result["total_persisted"] == 2

    # Verify SQLite database directly
    db_path = resolve_paths().fixture(fixture_id, dialect="sqlite").db_path
    assert db_path.is_file()

    executor = make_sql_executor(db_path, dialect=SqlDialect.SQLITE)
    try:
        blobs = executor.query(
            executor.compiler.compile(
                Select(
                    source=Table(schemas.DOCUMENT_BLOBS_TABLE),
                    projection=(col("doc_id"), col("raw_payload")),
                )
            )
        )
    finally:
        executor.close()

    assert len(blobs) == 2
    decompressed = [schemas.decompress_payload(b["raw_payload"]) for b in blobs]
    assert b"<html>doc1</html>" in decompressed
    assert b"<html>doc2</html>" in decompressed


def test_cli_fill_fixture_command(
    phase02_bundle: Path, capsys: pytest.CaptureFixture[str]
):
    fixture_id = f"cli-fix-{uuid.uuid4().hex[:8]}"
    # Fill with limit 1
    code = cli.main(
        [
            "fill-fixture",
            "--plan-dir",
            str(phase02_bundle),
            "--fixture-id",
            fixture_id,
            "--limit",
            "1",
            "--no-progress",
        ]
    )
    # The default http client might fail on mock URLs, but the command runs cleanly
    assert code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["fixture_id"] == fixture_id
    assert data["target_locators"] == 1


def test_fill_fixture_concurrent_workers_overlap(tmp_path: Path):
    bundle = _build_multi_doc_bundle(tmp_path / "plan", count=5)
    fixture_id = f"overlap-{uuid.uuid4().hex[:8]}"
    num_workers = 4
    client = BarrierHttpClient(_payload_urls(count=5), num_workers)

    result = fixture_builder.fill_fixture(
        bundle,
        fixture_id=fixture_id,
        http_client=client,
        workers=num_workers,
    )

    assert result["newly_fetched"] == 5
    assert result["total_persisted"] == 5
    # The barrier requires all workers to be active simultaneously.
    assert client.max_active == num_workers


def test_fill_fixture_worker_one_is_serial(tmp_path: Path):
    bundle = _build_multi_doc_bundle(tmp_path / "plan", count=3)
    fixture_id = f"serial-{uuid.uuid4().hex[:8]}"
    client = BarrierHttpClient(_payload_urls(count=3), 1)

    result = fixture_builder.fill_fixture(
        bundle,
        fixture_id=fixture_id,
        http_client=client,
        workers=1,
    )

    assert result["newly_fetched"] == 3
    assert result["total_persisted"] == 3
    assert client.max_active == 1


def test_fill_fixture_rejects_invalid_workers(tmp_path: Path):
    bundle = _build_multi_doc_bundle(tmp_path / "plan", count=2)
    fake_client = FakeHttpClient(_payload_urls(count=2))

    with pytest.raises(ValueError):
        fixture_builder.fill_fixture(
            bundle,
            fixture_id=f"bad-{uuid.uuid4().hex[:8]}",
            http_client=fake_client,
            workers=0,
        )


def test_fill_fixture_resume_does_not_refetch(tmp_path: Path):
    bundle = _build_multi_doc_bundle(tmp_path / "plan", count=3)
    fixture_id = f"resume-{uuid.uuid4().hex[:8]}"

    # First pass: only one document is available.
    first_urls = {next(iter(_payload_urls(count=3)))}
    first_client = FakeHttpClient(
        {url: _payload_urls(count=3)[url] for url in first_urls}
    )
    first = fixture_builder.fill_fixture(
        bundle,
        fixture_id=fixture_id,
        http_client=first_client,
        workers=2,
    )
    assert first["total_persisted"] == 1

    # Second pass: all documents are available. Stored blobs must not be
    # refetched; previously-failed documents remain skipped by resumption.
    second_client = TrackingHttpClient(_payload_urls(count=3))
    second = fixture_builder.fill_fixture(
        bundle,
        fixture_id=fixture_id,
        http_client=second_client,
        workers=2,
    )
    assert second["total_persisted"] == 1
    # No HTTP calls on resume: stored blobs and prior failures are skipped.
    assert second_client.calls == []


def test_cli_fill_fixture_workers_flag(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    bundle = _build_multi_doc_bundle(tmp_path / "plan", count=1)
    fixture_id = f"cli-w-{uuid.uuid4().hex[:8]}"
    code = cli.main(
        [
            "fill-fixture",
            "--plan-dir",
            str(bundle),
            "--fixture-id",
            fixture_id,
            "--limit",
            "1",
            "--workers",
            "2",
            "--no-progress",
        ]
    )
    assert code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["fixture_id"] == fixture_id
    assert data["target_locators"] == 1


def test_cli_fill_fixture_rejects_zero_workers(tmp_path: Path):
    bundle = _build_multi_doc_bundle(tmp_path / "plan", count=1)
    code = cli.main(
        [
            "fill-fixture",
            "--plan-dir",
            str(bundle),
            "--fixture-id",
            f"cli-bad-{uuid.uuid4().hex[:8]}",
            "--workers",
            "0",
            "--no-progress",
        ]
    )
    assert code == 2
