"""S4 scheduling, chunk commit, resume, and retry contracts.

All tests run offline against fake HTTP clients injected at the transport seam.
"""

from __future__ import annotations

from concurrent.futures import Future
from pathlib import Path

import pytest

from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.foundation.runtime.resources import RuntimeResourceProfile
from edgar_sec.infra.sec_http.metrics import HttpMetrics
from edgar_sec.pipelines.document_inventory import coordinator as coordinator_module
from edgar_sec.domain.document_inventory.models import IndexWorkItem
from edgar_sec.pipelines.document_inventory.broker import IndexPageBrokerClient
from edgar_sec.pipelines.document_inventory.checkpoint import (
    read_outcome_rows,
    validate_committed_chunk,
)
from edgar_sec.pipelines.document_inventory.worker import IndexWorkerFailure
from edgar_sec.pipelines.document_inventory.paths import inventory_run_paths
from edgar_sec.pipelines.document_inventory.run_manifest import (
    ManifestMismatchError,
    partition_into_chunks,
    read_run_manifest,
)
from edgar_sec.pipelines.document_inventory.coordinator import (
    _bounded_results,
    run_missing_accessions,
)
from tests.support import fixture_path

INDEX_HTML = fixture_path("document_inventory_index_page.html").read_bytes()

IDENTITY = {
    "parent_snapshot_id": "snap-1",
    "canonical_cohort_id": "cohort-1",
    "source_identity": "source-1",
    "parser_version": "parser-1",
    "chunk_size": 3,
    "refresh_mode": "normal",
    "fetch_mode": "live",
}


def _items(count: int) -> list[IndexWorkItem]:
    result = []
    for n in range(1, count + 1):
        accession = AccessionNumber.from_any(f"{n:010d}26000001")
        result.append(
            IndexWorkItem(
                accession=accession,
                index_url=(
                    "https://www.sec.gov/Archives/edgar/data/1/"
                    f"{accession.normalized}/{accession.normalized}-index.htm"
                ),
            )
        )
    return result


class _FakeHttp:
    """Offline transport double: serves canned pages, records every call."""

    def __init__(
        self,
        pages: dict[str, bytes] | None = None,
        failing: set[str] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.pages = pages or {}
        self.failing = failing or set()
        self.error = error
        self.calls: list[str] = []
        self.metrics = HttpMetrics()

    def peek_cache(self, url: str) -> bytes | None:
        return None

    def get_bytes(self, url: str, *, force_refresh: bool = False) -> bytes:
        self.calls.append(url)
        if url in self.failing:
            raise self.error or RuntimeError("429 rate limited: retries exhausted")
        return self.pages[url]


def _serving_http(items: list[IndexWorkItem], **kwargs: object) -> _FakeHttp:
    return _FakeHttp({item.index_url: INDEX_HTML for item in items}, **kwargs)  # type: ignore[arg-type]


def _outcome_by_accession(paths, chunk_id: str, attempt: str) -> dict[str, dict]:
    return {
        row["accession"]: row for row in read_outcome_rows(paths, chunk_id, attempt)
    }


# --- bounded scheduling ---------------------------------------------------


class _ImmediatePool:
    """Completes every future at submit; tracks outstanding in-flight tasks."""

    def __init__(self) -> None:
        self.outstanding = 0
        self.max_outstanding = 0

    def submit(self, fn, item, broker, force_refresh):  # noqa: ANN001
        self.outstanding += 1
        self.max_outstanding = max(self.max_outstanding, self.outstanding)
        future: Future = Future()
        future.set_result(
            IndexWorkerFailure(item.accession, "worker_error", "synthetic")
        )
        original_result = future.result

        def tracked(*args, **kwargs):  # noqa: ANN001, ANN202
            self.outstanding -= 1
            return original_result(*args, **kwargs)

        future.result = tracked  # type: ignore[method-assign]
        return future


def test_in_flight_stays_within_worker_budget() -> None:
    items = _items(10)
    broker = IndexPageBrokerClient(Path("/nonexistent/b.sock"))
    pool = _ImmediatePool()
    results = list(_bounded_results(items, broker, 3, False, pool))
    assert pool.max_outstanding <= 3
    assert len(results) == len(items)


class _CompletionOrderPool:
    """First submission stays pending; later ones complete on arrival."""

    def __init__(self, total: int) -> None:
        self.total = total
        self.submitted = 0
        self.pending: list[tuple[IndexWorkItem, Future]] = []

    def submit(self, fn, item, broker, force_refresh):  # noqa: ANN001
        future: Future = Future()
        self.submitted += 1
        self.pending.append((item, future))
        if self.submitted == 1:
            return future
        if self.submitted == self.total:
            for pend_item, pend_future in self.pending:
                if not pend_future.done():
                    pend_future.set_result(
                        IndexWorkerFailure(
                            pend_item.accession, "worker_error", "synthetic"
                        )
                    )
        else:
            future.set_result(
                IndexWorkerFailure(item.accession, "worker_error", "synthetic")
            )
        return future


def test_results_stream_in_completion_not_submission_order() -> None:
    items = _items(4)
    broker = IndexPageBrokerClient(Path("/nonexistent/b.sock"))
    pool = _CompletionOrderPool(total=4)
    order = [
        str(result.accession)
        for result in _bounded_results(items, broker, 2, False, pool)
    ]
    # The first submit stays pending, so the second submission completes first.
    assert order[0] == str(items[1].accession)
    assert set(order) == {str(item.accession) for item in items}


class _OneBoomPool:
    """Fails one designated accession; sibling futures complete normally."""

    def __init__(self, boom: AccessionNumber) -> None:
        self.boom = boom

    def submit(self, fn, item, broker, force_refresh):  # noqa: ANN001
        future: Future = Future()
        if item.accession == self.boom:
            future.set_exception(RuntimeError("child crashed"))
        else:
            future.set_result(
                IndexWorkerFailure(item.accession, "worker_error", "synthetic")
            )
        return future


def test_failed_future_does_not_erase_siblings() -> None:
    items = _items(4)
    broker = IndexPageBrokerClient(Path("/nonexistent/b.sock"))
    pool = _OneBoomPool(boom=items[2].accession)
    results = list(_bounded_results(items, broker, 2, False, pool))
    by_accession = {str(r.accession): r for r in results}
    assert len(results) == len(items)
    boom = by_accession[str(items[2].accession)]
    assert isinstance(boom, IndexWorkerFailure)
    assert boom.code == "worker_error"
    assert "child crashed" in boom.detail


class _BrokenPool:
    """Raises on submit after the first task, like a broken executor."""

    def __init__(self) -> None:
        self.submitted = 0

    def submit(self, fn, item, broker, force_refresh):  # noqa: ANN001
        self.submitted += 1
        if self.submitted > 1:
            raise RuntimeError("pool broken")
        future: Future = Future()
        future.set_result(
            IndexWorkerFailure(item.accession, "worker_error", "synthetic")
        )
        return future


def test_broken_pool_yields_typed_failures_for_every_member() -> None:
    items = _items(4)
    broker = IndexPageBrokerClient(Path("/nonexistent/b.sock"))
    results = list(_bounded_results(items, broker, 2, False, _BrokenPool()))
    assert len(results) == len(items)
    assert all(isinstance(result, IndexWorkerFailure) for result in results)


# --- coordinator runs -----------------------------------------------------


def test_run_commits_every_chunk_with_one_broker(tmp_path: Path, monkeypatch) -> None:
    items = _items(5)
    fake = _serving_http(items)
    paths = inventory_run_paths(tmp_path, "run-1")
    real_managed = coordinator_module.managed_broker
    calls = {"count": 0}

    def counting_managed(*args, **kwargs):  # noqa: ANN001, ANN202
        calls["count"] += 1
        return real_managed(*args, **kwargs)

    monkeypatch.setattr(coordinator_module, "managed_broker", counting_managed)
    summary = run_missing_accessions(
        items, IDENTITY, paths, http_client=fake, workers=1
    )
    assert calls["count"] == 1
    assert len(summary.chunks) == 2
    assert summary.committed_count == 2
    assert summary.refusal_count == 0
    assert set(fake.calls) == {item.index_url for item in items}
    for chunk in summary.chunks:
        validation = validate_committed_chunk(
            paths,
            chunk.chunk_id,
            run=read_run_manifest(paths),
            chunk=next(
                ci
                for ci in read_run_manifest(paths).chunk_identities
                if ci.chunk_id == chunk.chunk_id
            ),
        )
        assert validation.valid
    assert not list(paths.run_root.rglob("*.tmp"))
    runtime_dir = paths.artifacts_root / "runtime"
    assert not list(runtime_dir.glob("*.sock"))


def test_resume_skips_valid_chunks_without_network(tmp_path: Path) -> None:
    items = _items(4)
    first = _serving_http(items)
    paths = inventory_run_paths(tmp_path, "run-1")
    run_missing_accessions(items, IDENTITY, paths, http_client=first, workers=1)
    second = _serving_http(items)
    summary = run_missing_accessions(
        items, IDENTITY, paths, http_client=second, workers=1
    )
    assert all(chunk.resumed for chunk in summary.chunks)
    assert second.calls == []


def test_mismatched_identity_refuses_before_first_request(tmp_path: Path) -> None:
    items = _items(3)
    first = _serving_http(items)
    paths = inventory_run_paths(tmp_path, "run-1")
    run_missing_accessions(items, IDENTITY, paths, http_client=first, workers=1)
    second = _serving_http(items)
    changed = {**IDENTITY, "parser_version": "parser-2"}
    with pytest.raises(ManifestMismatchError):
        run_missing_accessions(items, changed, paths, http_client=second, workers=1)
    assert second.calls == []


def test_corrupt_attempt_is_recomputed_whole(tmp_path: Path) -> None:
    items = _items(3)
    first = _serving_http(items)
    paths = inventory_run_paths(tmp_path, "run-1")
    before = run_missing_accessions(
        items, IDENTITY, paths, http_client=first, workers=1
    )
    chunk = before.chunks[0]
    outcomes = paths.attempt_outcomes_path(chunk.chunk_id, chunk.attempt_id)
    outcomes.write_bytes(outcomes.read_bytes() + b"tampered")
    second = _serving_http(items)
    after = run_missing_accessions(
        items, IDENTITY, paths, http_client=second, workers=1
    )
    assert after.chunks[0].attempt_id != chunk.attempt_id
    assert set(second.calls) == {item.index_url for item in items}


def test_default_resume_keeps_retryable_failures_without_refetch(
    tmp_path: Path,
) -> None:
    items = _items(3)
    failing_url = items[1].index_url
    first = _serving_http(items, failing={failing_url})
    paths = inventory_run_paths(tmp_path, "run-1")
    run1 = run_missing_accessions(items, IDENTITY, paths, http_client=first, workers=1)
    assert run1.refusal_count == 1
    second = _serving_http(items)
    run2 = run_missing_accessions(items, IDENTITY, paths, http_client=second, workers=1)
    assert second.calls == []
    assert run2.chunks[0].attempt_id == run1.chunks[0].attempt_id


def test_retry_replaces_only_failed_accessions(tmp_path: Path) -> None:
    items = _items(3)
    failing_url = items[1].index_url
    first = _serving_http(items, failing={failing_url})
    paths = inventory_run_paths(tmp_path, "run-1")
    run1 = run_missing_accessions(items, IDENTITY, paths, http_client=first, workers=1)
    chunk_id = run1.chunks[0].chunk_id
    prior_rows = _outcome_by_accession(paths, chunk_id, run1.chunks[0].attempt_id)
    assert prior_rows[str(items[1].accession)]["status"] == "fetch_failed"

    second = _serving_http(items)
    run2 = run_missing_accessions(
        items,
        IDENTITY,
        paths,
        http_client=second,
        workers=1,
        retry_failures=True,
    )
    assert second.calls == [failing_url]
    assert run2.chunks[0].attempt_id != run1.chunks[0].attempt_id
    assert run2.refusal_count == 0
    fresh_rows = _outcome_by_accession(paths, chunk_id, run2.chunks[0].attempt_id)
    assert fresh_rows[str(items[1].accession)]["status"] == "parsed"
    carried = fresh_rows[str(items[0].accession)]
    assert carried["page_sha256"] == prior_rows[str(items[0].accession)]["page_sha256"]
    old = paths.attempt_outcomes_path(chunk_id, run1.chunks[0].attempt_id)
    assert old.is_file()


def test_one_failed_accession_keeps_its_siblings(tmp_path: Path) -> None:
    items = _items(3)
    failing_url = items[0].index_url
    fake = _serving_http(items, failing={failing_url})
    paths = inventory_run_paths(tmp_path, "run-1")
    summary = run_missing_accessions(
        items, IDENTITY, paths, http_client=fake, workers=1
    )
    rows = _outcome_by_accession(
        paths, summary.chunks[0].chunk_id, summary.chunks[0].attempt_id
    )
    assert len(rows) == len(items)
    assert rows[str(items[0].accession)]["status"] == "fetch_failed"
    assert rows[str(items[1].accession)]["status"] == "parsed"
    assert rows[str(items[2].accession)]["status"] == "parsed"
    assert summary.refusal_count == 1


def test_reclaim_runs_during_coordinator(tmp_path: Path, monkeypatch) -> None:
    items = _items(2)
    fake = _serving_http(items)
    paths = inventory_run_paths(tmp_path, "run-1")
    count = {"n": 0}

    def counting_reclaim() -> None:
        count["n"] += 1

    monkeypatch.setattr(coordinator_module, "reclaim", counting_reclaim)
    run_missing_accessions(items, IDENTITY, paths, http_client=fake, workers=1)
    assert count["n"] >= len(items)


def test_pool_size_comes_from_resource_profile(tmp_path: Path, monkeypatch) -> None:
    items = _items(4)
    fake = _serving_http(items)
    paths = inventory_run_paths(tmp_path, "run-1")
    created: list[dict] = []

    class _RecordingPool:
        def __init__(self, **kwargs) -> None:
            created.append(kwargs)

        def submit(self, fn, *args):  # noqa: ANN001
            future: Future = Future()
            try:
                future.set_result(fn(*args))
            except BaseException as exc:  # noqa: BLE001
                future.set_exception(exc)
            return future

        def shutdown(self, wait: bool = True) -> None:
            return None

    monkeypatch.setattr(coordinator_module, "ProcessPoolExecutor", _RecordingPool)
    profile = RuntimeResourceProfile(
        cpu_cores=2,
        workers=3,
        threads=2,
        memory_limit="512MB",
        temp_directory=str(tmp_path),
        available_memory_bytes=1 << 30,
        worker_memory_mib=512,
        worker_memory_safety=0.9,
    )
    summary = run_missing_accessions(
        items, IDENTITY, paths, http_client=fake, profile=profile
    )
    assert created and created[0]["max_workers"] == 3
    assert summary.committed_count == 2


def test_single_worker_never_builds_a_pool(tmp_path: Path, monkeypatch) -> None:
    items = _items(2)
    fake = _serving_http(items)
    paths = inventory_run_paths(tmp_path, "run-1")

    def explode(**_kwargs):  # noqa: ANN202
        raise AssertionError("pool must not be created for one worker")

    monkeypatch.setattr(coordinator_module, "ProcessPoolExecutor", explode)
    summary = run_missing_accessions(
        items, IDENTITY, paths, http_client=fake, workers=1
    )
    assert summary.committed_count == 1


def test_spawn_pool_executes_chunks(tmp_path: Path) -> None:
    items = _items(4)
    fake = _serving_http(items)
    paths = inventory_run_paths(tmp_path, "run-spawn")
    summary = run_missing_accessions(
        items,
        {**IDENTITY, "chunk_size": 2},
        paths,
        http_client=fake,
        workers=2,
    )
    assert len(summary.chunks) == 2
    assert summary.committed_count == 2
    assert set(fake.calls) == {item.index_url for item in items}
    assert not list(paths.run_root.rglob("*.tmp"))
    assert not list(paths.run_root.rglob("*.sqlite"))


def test_partition_matches_manifest_chunk_ids() -> None:
    items = _items(5)
    chunks = partition_into_chunks(items, chunk_size=2)
    assert [chunk_id for chunk_id, *_ in chunks] == [
        chunk_id
        for chunk_id, *_ in partition_into_chunks(list(reversed(items)), chunk_size=2)
    ]
