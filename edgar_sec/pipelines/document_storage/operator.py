"""Run orchestration: process chunks, resolve delegations, merge, publish.

Delegation runs between the two because its output is itself a chunk: an exhibit
resolved from a stub must land in the same snapshot as its primary.
"""

from __future__ import annotations

import json
import logging
import secrets
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from edgar_sec.domain.document.models import DocumentLocator, FilingOccurrence
from edgar_sec.foundation.hashing import file_sha256, sha256_text
from edgar_sec.foundation.runtime.fixtures import validate_fixture_component
from edgar_sec.foundation.runtime.resources import RuntimeResourceProfile
from edgar_sec.foundation.serialization import canonical_json
from edgar_sec.infra.storage.atomic import atomic_write_json
from edgar_sec.pipelines.document_storage.delegation import (
    REFETCH_ACTION,
    DelegatedExhibit,
    resolve_delegated_exhibit,
    write_exhibit_snapshot,
)
from edgar_sec.pipelines.document_storage.catalog_execution import (
    process_catalog_chunks,
)
from edgar_sec.pipelines.document_storage.catalog_plan import CatalogPlan
from edgar_sec.pipelines.document_storage.fetching import make_archive_fetcher
from edgar_sec.pipelines.document_storage.fixture_operator import FixtureOperatorError
from edgar_sec.pipelines.document_storage.merger import (
    MergeResult,
    publish_snapshot,
)
from edgar_sec.pipelines.document_storage.processor import (
    DocumentProcessor,
    FilingProcessor,
)
from edgar_sec.pipelines.document_storage.execution import (
    ChunkResult,
    process_chunk_stream,
    process_chunks,
)
from edgar_sec.pipelines.document_storage.checkpoint import (
    chunk_fingerprint,
    validate_chunk_snapshot,
    _stamp_fingerprint,
)
from edgar_sec.pipelines.document_storage.paths import (
    DocumentStoragePaths,
    catalog_delegation_path,
)
from edgar_sec.pipelines.document_storage.run_manifest import (
    RunManifestError,
    catalog_run_identity,
    create_or_validate_manifest,
)
from edgar_sec.pipelines.document_storage.work_order import WorkOrder

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
    run_status: str | None = None
    fresh_chunk_count: int = 0
    resumed_chunk_count: int = 0
    reused_chunk_count: int = 0
    exhibits_resolved_count: int | None = None

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

    @property
    def candidate_eligible_count(self) -> int:
        """Requested locators whose filing date falls inside the 2000-2004 window."""
        return sum(chunk.candidate_eligible_count for chunk in self.chunks)

    @property
    def bundle_candidate_count(self) -> int:
        """The subset that also reads as a statutory exhibit rather than the form."""
        return sum(chunk.bundle_candidate_count for chunk in self.chunks)

    @property
    def candidate_date_unresolved_count(self) -> int:
        """Requested locators with no agreed parseable filing date.

        Reported so a fail-closed date reads as a measured condition rather than as an
        unexplained zero in the eligible count.
        """
        return sum(chunk.candidate_date_unresolved_count for chunk in self.chunks)

    def to_dict(self) -> dict[str, Any]:
        """Render the report for a manifest or a CLI summary."""
        report = {
            "run_id": self.run_id,
            "snapshot_id": self.snapshot_id,
            "artifact_path": str(self.artifact_path),
            "row_count": self.merge.snapshot.row_count,
            "chunk_count": self.merge.snapshot.chunk_count,
            "total_documents": self.total_documents,
            "failed_documents": self.failed_documents,
            "candidate_eligible_count": self.candidate_eligible_count,
            "bundle_candidate_count": self.bundle_candidate_count,
            "candidate_date_unresolved_count": self.candidate_date_unresolved_count,
            "exhibits_resolved": (
                len(self.exhibits)
                if self.exhibits_resolved_count is None
                else self.exhibits_resolved_count
            ),
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "ok": self.ok,
            "warnings": list(self.merge.warnings),
        }
        if self.run_status is not None:
            report.update(
                {
                    "run_status": self.run_status,
                    "fresh_chunk_count": self.fresh_chunk_count,
                    "resumed_chunk_count": self.resumed_chunk_count,
                    "reused_chunk_count": self.reused_chunk_count,
                }
            )
        return report


def new_run_id(prefix: str = "run") -> str:
    """Return a sortable, unique run identity.

    Microseconds plus a random suffix: a snapshot id derives from the run id, so a
    collision would make a new run look like a republication of the first.
    """
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")
    return f"{prefix}-{stamp}-{secrets.token_hex(3)}"


def make_fetcher(
    mode: FetchMode,
    paths: DocumentStoragePaths,
    *,
    fixture_id: str | Sequence[str] | None = None,
    http_client: Any | None = None,
    broker_socket: str | Path | None = None,
    cache_reader: Any | None = None,
) -> Any:
    """Build the fetcher a run's mode calls for, with repository paths resolved.

    In fixture mode a missing fixture id is an error, not an empty run that would
    publish an empty snapshot looking like a successful acquisition.
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
                safe_id = validate_fixture_component(raw_id, "fixture_id")
            except ValueError as exc:
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
    paths: DocumentStoragePaths,
    run_id: str,
    chunk_ids: Sequence[str] = (),
    locators_by_chunk: Mapping[str, Sequence[DocumentLocator]] | None = None,
    occurrences_by_chunk: Mapping[str, Sequence[FilingOccurrence]] | None = None,
    work_order: WorkOrder | None = None,
    catalog_plan: CatalogPlan | None = None,
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

    Exactly one input mode applies: a replayable ``work_order``, a catalog bundle,
    or explicit chunk ids.
    """
    started_at = datetime.now(UTC).isoformat(timespec="seconds")
    streaming = work_order is not None
    run_status: str | None = None
    if catalog_plan is not None:
        streaming = True
        if work_order is not None and work_order is not catalog_plan:
            raise OperatorError("catalog_plan must be the catalog work order")
    elif streaming:
        if work_order.chunk_count < 1:
            raise OperatorError("work order yields no chunks")
        _refuse_existing_run(paths, run_id)
    elif not chunk_ids:
        raise OperatorError("at least one chunk id is required")

    effective_processor = processor if processor is not None else FilingProcessor()
    if catalog_plan is not None:
        fixture_ids = (
            (fixture_id,)
            if isinstance(fixture_id, str)
            else tuple(str(item) for item in (fixture_id or ()))
        )
        identity = catalog_run_identity(
            catalog_plan,
            run_id=run_id,
            mode=mode,
            fixture_ids=fixture_ids,
            processor=effective_processor,
        )
        try:
            run_status = create_or_validate_manifest(
                paths.run_dir(run_id), run_id, identity
            )
        except RunManifestError as exc:
            raise OperatorError(str(exc)) from exc
        if mode == "fixture":
            from edgar_sec.pipelines.document_storage.fixture_operator import (
                verify_fixture_lineage,
            )

            for selected_fixture in fixture_ids:
                verify_fixture_lineage(
                    paths,
                    selected_fixture,
                    target_reference=catalog_plan.metadata.plan_id,
                    target_fingerprint=catalog_plan.metadata.selection_fingerprint,
                )
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
        progress(
            {
                "stage": "chunks",
                "run_id": run_id,
                "count": work_order.chunk_count if streaming else len(chunk_ids),
            }
        )
    if catalog_plan is not None:
        chunk_results = process_catalog_chunks(
            catalog_plan,
            fetcher=active_fetcher,
            processor=effective_processor,
            chunks_dir=chunks_dir,
            workers=workers,
            profile=profile,
        )
    elif streaming:
        assert work_order is not None
        chunk_results = process_chunk_stream(
            work_order,
            fetcher=active_fetcher,
            processor=effective_processor,
            chunks_dir=chunks_dir,
            workers=workers,
            profile=profile,
        )
    else:
        chunk_results = process_chunks(
            chunk_ids,
            locators_by_chunk or {},
            occurrences_by_chunk or {},
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
    exhibits_resolved_count: int | None = None
    if catalog_plan is not None:
        exhibits, exhibits_resolved_count = _run_catalog_delegation(
            chunk_results,
            catalog_plan,
            fetcher=active_fetcher,
            processor=effective_processor,
            chunks_dir=chunks_dir,
        )
    elif streaming:
        assert work_order is not None
        exhibits = _run_delegation_from_work_order(
            chunk_results,
            work_order,
            fetcher=active_fetcher,
            processor=effective_processor,
            chunks_dir=chunks_dir,
        )
    else:
        exhibits = _run_delegation(
            chunk_results,
            locators_by_chunk or {},
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
        reuse_existing=catalog_plan is not None,
    )
    finished_at = datetime.now(UTC).isoformat(timespec="seconds")
    return RunReport(
        run_id=run_id,
        chunks=chunk_results,
        merge=merge,
        exhibits=exhibits,
        started_at=started_at,
        finished_at=finished_at,
        run_status=run_status,
        fresh_chunk_count=sum(
            chunk.execution_state == "fresh" for chunk in chunk_results
        )
        if catalog_plan is not None
        else 0,
        resumed_chunk_count=sum(
            chunk.execution_state == "resumed" for chunk in chunk_results
        )
        if catalog_plan is not None
        else 0,
        reused_chunk_count=sum(
            chunk.execution_state == "reused" for chunk in chunk_results
        )
        if catalog_plan is not None
        else 0,
        exhibits_resolved_count=exhibits_resolved_count,
    )


def _refuse_existing_run(paths: DocumentStoragePaths, run_id: str) -> None:
    """Refuse a work-order run whose run directory already holds state.

    Nothing is deleted; reusing an interrupted run belongs to a resumability contract
    this path does not make.
    """
    run_dir = paths.run_dir(run_id)
    if run_dir.exists():
        raise OperatorError(
            f"run directory already exists: {run_dir}; "
            "use a new run id rather than reusing a catalog plan run"
        )


def _partial_ok(results: Sequence[ChunkResult]) -> bool:
    """Return whether at least one document was actually acquired and stored.

    Measured on ``normalized_count``: a failed acquisition still wrote a row, so
    counting rows would let a wholly failed run overwrite a good snapshot.
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
    """Resolve every stub decision a worker reported, publishing them as a chunk."""
    by_key: dict[str, DocumentLocator] = {
        locator.document_locator_key: locator
        for locators in locators_by_chunk.values()
        for locator in locators
    }
    return _publish_delegations(
        chunk_results,
        by_key,
        fetcher=fetcher,
        processor=processor,
        chunks_dir=chunks_dir,
    )


def _run_delegation_from_work_order(
    chunk_results: Sequence[ChunkResult],
    work_order: WorkOrder,
    *,
    fetcher: Any,
    processor: DocumentProcessor,
    chunks_dir: Path,
) -> tuple[DelegatedExhibit, ...]:
    """Resolve delegations by re-reading only the locators a worker asked for.

    A work order is replayable precisely so this pass does not rebuild the plan-wide
    locator mapping the mapping path can afford.
    """
    wanted = [
        target.document_locator_key
        for result in chunk_results
        for target in result.delegations
    ]
    return _publish_delegations(
        chunk_results,
        work_order.locators_by_key(wanted),
        fetcher=fetcher,
        processor=processor,
        chunks_dir=chunks_dir,
    )


def _run_catalog_delegation(
    chunk_results: Sequence[ChunkResult],
    work_order: WorkOrder,
    *,
    fetcher: Any,
    processor: DocumentProcessor,
    chunks_dir: Path,
) -> tuple[tuple[DelegatedExhibit, ...], int]:
    processor_fingerprint = chunk_results[0].processor_fingerprint
    sources = []
    wanted: list[str] = []
    for result in sorted(chunk_results, key=lambda item: item.chunk_id):
        sidecar = catalog_delegation_path(result.output_path)
        if not sidecar.is_file():
            raise OperatorError(f"catalog delegation sidecar is missing: {sidecar}")
        sources.append({"chunk_id": result.chunk_id, "sha256": file_sha256(sidecar)})
        wanted.extend(target.document_locator_key for target in result.delegations)
    input_identity = sha256_text(
        canonical_json(
            {"processor_fingerprint": processor_fingerprint, "sources": sources}
        )
    )
    output_path = chunks_dir / "chunk-delegated.parquet"
    state_path = chunks_dir / "chunk-delegated.state.json"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        meta = validate_chunk_snapshot(output_path)
        if (
            isinstance(state, dict)
            and state.get("version") == 1
            and state.get("input_identity") == input_identity
            and state.get("processor_fingerprint") == processor_fingerprint
            and state.get("output_sha256") == file_sha256(output_path)
            and state.get("row_count") == meta["num_rows"]
            and chunk_fingerprint(output_path) == processor_fingerprint
        ):
            return (), int(state["row_count"])
    except (OSError, ValueError, json.JSONDecodeError):
        pass

    exhibits = _publish_delegations(
        chunk_results,
        work_order.locators_by_key(wanted),
        fetcher=fetcher,
        processor=processor,
        chunks_dir=chunks_dir,
        write_empty=True,
    )
    _stamp_fingerprint(output_path, processor_fingerprint)
    row_count = validate_chunk_snapshot(output_path)["num_rows"]
    atomic_write_json(
        state_path,
        {
            "version": 1,
            "input_identity": input_identity,
            "processor_fingerprint": processor_fingerprint,
            "output_sha256": file_sha256(output_path),
            "row_count": row_count,
        },
        canonical=True,
    )
    return exhibits, row_count


def _publish_delegations(
    chunk_results: Sequence[ChunkResult],
    by_key: Mapping[str, DocumentLocator],
    *,
    fetcher: Any,
    processor: DocumentProcessor,
    chunks_dir: Path,
    write_empty: bool = False,
) -> tuple[DelegatedExhibit, ...]:
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
    if exhibits or write_empty:
        write_exhibit_snapshot(chunks_dir / "chunk-delegated.parquet", exhibits)
    return exhibits


class _StubDecision:
    """The minimum a delegation pass needs from a worker's evaluator verdict."""

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
