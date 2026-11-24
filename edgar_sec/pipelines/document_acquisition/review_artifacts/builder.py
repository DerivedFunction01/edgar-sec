from __future__ import annotations

import multiprocessing
import os
import shutil
import tempfile
from collections import deque
from concurrent.futures import Future, ProcessPoolExecutor
from pathlib import Path

from tqdm.auto import tqdm

from edgar_sec.foundation.runtime.resources import derive_resources

from edgar_sec.foundation.runtime.memory import reclaim
from edgar_sec.foundation.serialization import canonical_json
from edgar_sec.infra.storage.atomic import atomic_write_text
from edgar_sec.infra.storage.review.paths import (
    PIPELINE_REVIEW_MANIFEST_FILE,
    ReviewPaths,
)
from edgar_sec.pipelines.document_acquisition.fixture_store.discovery import (
    FixtureCaseMetadata,
)
from edgar_sec.pipelines.document_acquisition.fixture_store.reader import (
    list_fixture_cases,
)
from edgar_sec.pipelines.document_acquisition.paths import AcquisitionPaths
from edgar_sec.pipelines.document_acquisition.review_artifacts.case_execution import (
    _manifest_record,
    _process_review_case_worker,
)
from edgar_sec.pipelines.document_acquisition.review_artifacts.case_processing import (
    _case_id,
)
from edgar_sec.pipelines.document_acquisition.review_artifacts.models import (
    ProcessingReviewArtifact,
    ReviewRunResult,
    ReviewSummary,
)


_RECLAIM_INTERVAL = 25


def build_review_artifacts(
    fixture_id: str,
    output: str | os.PathLike[str],
    *,
    paths: AcquisitionPaths,
    limit: int | None = None,
    workers: int | None = None,
    no_progress: bool = False,
) -> ReviewRunResult:
    if limit is not None and limit < 1:
        raise ValueError("limit must be positive")
    cases = list(list_fixture_cases(paths, fixture_id=fixture_id))
    if limit is not None:
        cases = cases[:limit]
    if not cases:
        raise ValueError("fixture has no parser-body cases")

    resources = derive_resources()
    if workers is not None and workers < 1:
        raise ValueError("workers must be positive")
    worker_count = (
        min(resources.workers, resources.worker_ceiling)
        if workers is None
        else min(workers, resources.worker_ceiling)
    )
    worker_count = max(1, min(worker_count, len(cases)))

    requested_output = Path(output).expanduser()
    if requested_output.is_symlink():
        raise ValueError("review output must not be a symlink")
    output_root = requested_output.resolve()
    if output_root.exists() and (
        not output_root.is_dir() or any(output_root.iterdir())
    ):
        raise ValueError(
            f"review output must be a new or empty directory: {output_root}"
        )
    output_root.mkdir(parents=True, exist_ok=True)
    review_paths = ReviewPaths(output_root, PIPELINE_REVIEW_MANIFEST_FILE)
    review_paths.case_staging_root().mkdir(parents=True, exist_ok=True)
    records = []
    counts = {"complete": 0, "fixture_verification_failure": 0, "execution_error": 0}

    if worker_count == 1:
        with tqdm(
            cases,
            desc="Parser review",
            unit="case",
            dynamic_ncols=True,
            disable=no_progress,
        ) as pbar:
            for case in pbar:
                case_root = review_paths.case_dir(_case_id(case))
                staging_root = Path(
                    tempfile.mkdtemp(
                        prefix="case-", dir=review_paths.case_staging_root()
                    )
                )
                st, art, err = _process_review_case_worker(
                    case, paths, case_root, staging_root, review_paths
                )
                counts[st] += 1
                records.append(
                    _manifest_record(
                        case,
                        review_paths.review_id,
                        review_paths,
                        status=st,
                        output=art,
                        error=err,
                    )
                )
                if (
                    counts["complete"]
                    + counts["fixture_verification_failure"]
                    + counts["execution_error"]
                ) % _RECLAIM_INTERVAL == 0:
                    reclaim()
    else:
        executor = ProcessPoolExecutor(
            max_workers=worker_count,
            mp_context=multiprocessing.get_context("spawn"),
        )
        pending: deque[
            tuple[
                FixtureCaseMetadata,
                Future[tuple[str, ProcessingReviewArtifact | None, str | None]],
            ]
        ] = deque()

        def _drain_oldest(pbar) -> None:
            c, fut = pending.popleft()
            try:
                st, art, err = fut.result()
            except Exception as exc:
                st, art, err = "execution_error", None, str(exc)
            counts[st] += 1
            records.append(
                _manifest_record(
                    c,
                    review_paths.review_id,
                    review_paths,
                    status=st,
                    output=art,
                    error=err,
                )
            )
            pbar.update(1)
            processed = (
                counts["complete"]
                + counts["fixture_verification_failure"]
                + counts["execution_error"]
            )
            if processed % _RECLAIM_INTERVAL == 0:
                reclaim()

        try:
            with tqdm(
                total=len(cases),
                desc="Parser review",
                unit="case",
                dynamic_ncols=True,
                disable=no_progress,
            ) as pbar:
                for case in cases:
                    case_root = review_paths.case_dir(_case_id(case))
                    staging_root = Path(
                        tempfile.mkdtemp(
                            prefix="case-", dir=review_paths.case_staging_root()
                        )
                    )
                    fut = executor.submit(
                        _process_review_case_worker,
                        case,
                        paths,
                        case_root,
                        staging_root,
                        review_paths,
                    )
                    pending.append((case, fut))
                    if len(pending) >= worker_count * 2:
                        _drain_oldest(pbar)

                while pending:
                    _drain_oldest(pbar)
        except KeyboardInterrupt:
            executor.shutdown(wait=False, cancel_futures=True)
            raise
        finally:
            executor.shutdown(wait=True)

    manifest = "".join(canonical_json(record) + "\n" for record in records)
    atomic_write_text(review_paths.manifest_path, manifest)
    shutil.rmtree(review_paths.case_staging_root(), ignore_errors=True)
    summary = ReviewSummary(
        total=len(records),
        completed=counts["complete"],
        fixture_verification_failure=counts["fixture_verification_failure"],
        execution_error=counts["execution_error"],
    )
    return ReviewRunResult(
        review_id=review_paths.review_id,
        output_root=output_root,
        summary=summary,
        exit_code=0
        if summary.fixture_verification_failure + summary.execution_error == 0
        else 1,
    )


__all__ = [
    "build_review_artifacts",
]
