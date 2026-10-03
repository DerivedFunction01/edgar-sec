"""Run orchestration: acquire, delegate, merge, publish.

One operator owns the order of a document-storage run, and it owns nothing else.
Each step is a call into a module that can be exercised on its own, so the
operator is a short readable sequence rather than the place where the work
happens.

    1. process chunks        (worker; resumable, parallel)
    2. resolve delegations    (exhibit second pass, bounded)
    3. merge and publish      (immutable snapshot + current pointer)

Delegation runs between the two because its output is itself a chunk: an exhibit
resolved from a stub must be merged into the same snapshot as its primary, or
the snapshot would claim a filing is complete when its substance sits in an
unpublished file.
"""

from __future__ import annotations

import logging
import secrets
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from edgar_sec.domain.document.models import DocumentLocator, FilingOccurrence
from edgar_sec.foundation.runtime.paths import ProjectPaths
from edgar_sec.foundation.runtime.resources import RuntimeResourceProfile
from edgar_sec.pipelines.document_storage.delegation import (
    REFETCH_ACTION,
    DelegatedExhibit,
    resolve_delegated_exhibit,
    write_exhibit_snapshot,
)
from edgar_sec.pipelines.document_storage.fetching import make_archive_fetcher
from edgar_sec.pipelines.document_storage.fixture_operator import (
    FixtureOperatorError,
    validate_fixture_id,
)
from edgar_sec.pipelines.document_storage.merger import (
    MergeResult,
    publish_snapshot,
)
from edgar_sec.pipelines.document_storage.processor import (
    DocumentProcessor,
    FilingProcessor,
)
from edgar_sec.pipelines.document_storage.worker import (
    ChunkResult,
    process_chunks,
)

log = logging.getLogger("document_storage.operator")

FetchMode = str


class OperatorError(RuntimeError):
    """A document-storage run could not complete."""


@dataclass(frozen=True, slots=True)
class RunReport:
    """What one run produced."""

    run_id: str
    chunks: tuple[ChunkResult, ...]
    merge: MergeResult
    exhibits: tuple[DelegatedExhibit, ...]
    started_at: str
    finished_at: str

    @property
    def snapshot_id(self) -> str:
        return self.merge.snapshot.snapshot_id

    @property
    def artifact_path(self) -> Path:
        return self.merge.snapshot.artifact_path

    @property
    def ok(self) -> bool:
        return all(chunk.ok for chunk in self.chunks)

    @property
    def total_documents(self) -> int:
        return sum(chunk.document_count for chunk in self.chunks)

    @property
    def failed_documents(self) -> int:
        return sum(chunk.failed_count + chunk.missing_count for chunk in self.chunks)

    def to_dict(self) -> dict[str, Any]:
        """Render the report for a manifest or a CLI summary."""
        return {
            "run_id": self.run_id,
            "snapshot_id": self.snapshot_id,
            "artifact_path": str(self.artifact_path),
            "row_count": self.merge.snapshot.row_count,
            "chunk_count": self.merge.snapshot.chunk_count,
            "total_documents": self.total_documents,
            "failed_documents": self.failed_documents,
            "exhibits_resolved": len(self.exhibits),
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "ok": self.ok,
            "warnings": list(self.merge.warnings),
        }


def new_run_id(prefix: str = "run") -> str:
    """Return a sortable, unique run identity.

    Microsecond resolution plus a short random suffix: two runs started in the
    same second must not share an identity, because a snapshot id is derived from
    the run id and a collision would make the second run look like a republication
    of the first.
    """
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")
    return f"{prefix}-{stamp}-{secrets.token_hex(3)}"


def make_fetcher(
    mode: FetchMode,
    paths: ProjectPaths,
    *,
    fixture_id: str | Sequence[str] | None = None,
    http_client: Any | None = None,
    broker_socket: str | Path | None = None,
    cache_reader: Any | None = None,
) -> Any:
    """Build the fetcher a run's mode calls for, with repository paths resolved.

    In fixture mode a missing fixture id is an error rather than an empty run:
    replaying a plan with no payloads would publish an empty snapshot that looks
    like a successful acquisition.
    """
    if mode == "fixture":
        fixture_ids = (
            [fixture_id] if isinstance(fixture_id, str) else list(fixture_id or ())
        )
        if not fixture_ids:
            raise OperatorError("fixture mode requires a fixture id")
        from edgar_sec.pipelines.document_storage.fixture_store import (
            FixtureStore,
            FixtureStoreError,
        )

        db_paths = []
        for raw_id in fixture_ids:
            try:
                safe_id = validate_fixture_id(raw_id)
            except FixtureOperatorError as exc:
                raise OperatorError(str(exc)) from exc
            db_path = paths.fixture_db_path(safe_id)
            try:
                with FixtureStore(db_path, read_only=True):
                    pass
            except FixtureStoreError as exc:
                raise OperatorError(str(exc)) from exc
            db_paths.append(db_path)
        return make_archive_fetcher("fixture", db_paths=db_paths)
    return make_archive_fetcher(
        mode,
        http_client=http_client,
        broker_socket=broker_socket,
        cache_reader=cache_reader,
    )


def run_document_storage(
    *,
    paths: ProjectPaths,
    run_id: str,
    chunk_ids: Sequence[str],
    locators_by_chunk: Mapping[str, Sequence[DocumentLocator]],
    occurrences_by_chunk: Mapping[str, Sequence[FilingOccurrence]],
    mode: FetchMode = "fixture",
    fixture_id: str | Sequence[str] | None = None,
    processor: DocumentProcessor | None = None,
    workers: int | None = None,
    profile: RuntimeResourceProfile | None = None,
    fetcher: Any | None = None,
    http_client: Any | None = None,
    broker_socket: str | Path | None = None,
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> RunReport:
    """Run the full document-storage pipeline for one set of chunks.

    Args:
        paths: resolved workspace layout.
        run_id: identity for this run's staging directory and snapshot.
        chunk_ids: chunks to process, in order.
        locators_by_chunk: documents to acquire per chunk.
        occurrences_by_chunk: provenance rows per chunk.
        mode: acquisition mode (``fixture``, ``broker``, or ``live``).
        fixture_id: fixture to replay from, required in fixture mode.
        processor: normalization backend; defaults to the filing processor.
        workers: explicit worker count; resolved from resources when absent.
        profile: pre-resolved cgroup-aware resource profile.
        fetcher: an explicit fetcher, bypassing mode resolution.
        http_client: injected HTTP client for live mode.
        broker_socket: broker socket path for broker mode.
        progress: optional per-stage callback.
    """
    started_at = datetime.now(UTC).isoformat(timespec="seconds")
    if not chunk_ids:
        raise OperatorError("at least one chunk id is required")

    effective_processor = processor if processor is not None else FilingProcessor()
    active_fetcher = (
        fetcher
        if fetcher is not None
        else make_fetcher(
            mode,
            paths,
            fixture_id=fixture_id,
            http_client=http_client,
            broker_socket=broker_socket,
        )
    )

    chunks_dir = paths.run_chunks_dir(run_id)
    chunks_dir.mkdir(parents=True, exist_ok=True)

    if progress is not None:
        progress({"stage": "chunks", "run_id": run_id, "count": len(chunk_ids)})
    chunk_results = process_chunks(
        chunk_ids,
        locators_by_chunk,
        occurrences_by_chunk,
        fetcher=active_fetcher,
        processor=effective_processor,
        chunks_dir=chunks_dir,
        workers=workers,
        profile=profile,
    )
    failed_chunks = [result.chunk_id for result in chunk_results if not result.ok]
    if failed_chunks and not _partial_ok(chunk_results):
        raise OperatorError(
            f"every chunk failed; refusing to publish: {sorted(failed_chunks)}"
        )

    if progress is not None:
        progress({"stage": "delegation", "run_id": run_id})
    exhibits = _run_delegation(
        chunk_results,
        locators_by_chunk,
        fetcher=active_fetcher,
        processor=effective_processor,
        chunks_dir=chunks_dir,
    )

    if progress is not None:
        progress({"stage": "publish", "run_id": run_id})
    merge = publish_snapshot(
        run_id=run_id,
        chunks_dir=chunks_dir,
        snapshots_root=paths.documents_root,
    )
    finished_at = datetime.now(UTC).isoformat(timespec="seconds")
    return RunReport(
        run_id=run_id,
        chunks=chunk_results,
        merge=merge,
        exhibits=exhibits,
        started_at=started_at,
        finished_at=finished_at,
    )


def _partial_ok(results: Sequence[ChunkResult]) -> bool:
    """Return whether at least one document was actually acquired and stored.

    Measured on ``normalized_count`` rather than row count: a chunk that
    recorded one failed acquisition still wrote a row, so counting rows would
    report a wholly failed run as a successful one and let it overwrite a good
    snapshot with a snapshot of nothing but failures.
    """
    return any(result.normalized_count for result in results)


def _run_delegation(
    chunk_results: Sequence[ChunkResult],
    locators_by_chunk: Mapping[str, Sequence[DocumentLocator]],
    *,
    fetcher: Any,
    processor: DocumentProcessor,
    chunks_dir: Path,
) -> tuple[DelegatedExhibit, ...]:
    """Resolve every stub decision a worker reported, publishing them as a chunk.

    Driven by the workers' own reports rather than by re-triage, so a primary is
    fetched and normalized exactly once per run.
    """
    by_key: dict[str, DocumentLocator] = {
        locator.document_locator_key: locator
        for locators in locators_by_chunk.values()
        for locator in locators
    }
    resolved: dict[str, DelegatedExhibit] = {}
    for result in sorted(chunk_results, key=lambda item: item.chunk_id):
        for target in result.delegations:
            locator = by_key.get(target.document_locator_key)
            if locator is None:
                log.warning(
                    "delegation target %s has no locator", target.document_locator_key
                )
                continue
            exhibit = resolve_delegated_exhibit(
                _StubDecision(target.target_exhibit),
                locator,
                fetcher=fetcher,
                processor=processor,
            )
            if exhibit is not None:
                resolved[exhibit.document_locator_key] = exhibit

    exhibits = tuple(resolved.values())
    if exhibits:
        write_exhibit_snapshot(chunks_dir / "chunk-delegated.parquet", exhibits)
    return exhibits


class _StubDecision:
    """The minimum a delegation pass needs from a worker's evaluator verdict.

    A stub decision is a fact the worker already established; carrying just the
    targeted exhibit keeps the delegation pass from re-running the evaluator, and
    keeps a full processed document out of the inter-stage contract.
    """

    __slots__ = ("metadata",)

    def __init__(self, target_exhibit: str) -> None:
        self.metadata = {
            "decision_action": REFETCH_ACTION,
            "target_exhibit": target_exhibit,
        }


__all__ = [
    "OperatorError",
    "RunReport",
    "make_fetcher",
    "new_run_id",
    "run_document_storage",
]
