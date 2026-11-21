"""Build one review run by replaying a fixture above the normalize line.

Stored products rebuild each filing's contexts through the
production function; the cascade and assembly then re-run on those
contexts — normalization never re-runs. Rows carry contract v1 shape.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from edgar_sec.engine.tables.extraction.assembly.context_production import DocumentInput
from edgar_sec.foundation.hashing import sha256_text
from edgar_sec.foundation.serialization import canonical_json
from edgar_sec.infra.storage.atomic import atomic_write_json, atomic_write_text
from edgar_sec.infra.storage.review.paths import (
    PIPELINE_REVIEW_MANIFEST_FILE,
    ReviewPaths,
    new_review_run_id,
    review_run_paths,
)
from edgar_sec.pipelines.table_classification.fixture_store.models import (
    DATASET,
    FixtureStoreError,
    ProductStamps,
)
from edgar_sec.pipelines.table_classification.fixture_store.reader import (
    list_fixture_cases,
    validate_stamps,
)
from edgar_sec.pipelines.table_classification.fixture_store.source import (
    FixtureFilingSource,
)
from edgar_sec.pipelines.table_classification.planner import FilingRow, Plan
from edgar_sec.pipelines.table_classification.schemas import (
    ROUTE_RAW,
    ROUTE_RENDER_TO_TXT,
)
from edgar_sec.pipelines.table_classification.worker import classify_products

from .models import ReviewRunResult, ReviewSummary

CLASSIFICATIONS_FILE = "classifications.json"
SUMMARY_FILE = "summary.json"


def _route_for(representation: str) -> str:
    """The render operation that produced a document's products.

    The vocabulary is engine/forms/render.py's operations: HTML
    payloads render to text; ASCII payloads ride raw.
    """
    return ROUTE_RENDER_TO_TXT if representation == "html" else ROUTE_RAW


def build_review_artifacts(
    artifacts_root: Path | str,
    fixture_id: str,
    output_root: Path | str | None = None,
    *,
    expected_stamps: ProductStamps | None = None,
    accessions: tuple[str, ...] | None = None,
    limit: int | None = None,
) -> ReviewRunResult:
    """Replay one fixture into a review artifact set under review-runs."""
    review_id = f"run-{new_review_run_id()}"
    if output_root is None:
        paths = review_run_paths(artifacts_root, DATASET, review_id)
    else:
        paths = ReviewPaths(Path(output_root), PIPELINE_REVIEW_MANIFEST_FILE)
        review_id = paths.review_id
    paths.root.mkdir(parents=True, exist_ok=True)
    paths.cases_root.mkdir(parents=True, exist_ok=True)

    stale = False
    if expected_stamps is not None:
        try:
            validate_stamps(artifacts_root, fixture_id, expected_stamps)
        except FixtureStoreError:
            stale = True

    selected = list_fixture_cases(artifacts_root, fixture_id)
    if accessions:
        wanted = set(accessions)
        selected = [item for item in selected if item.key.accession in wanted]
    if limit is not None:
        selected = selected[:limit]
    plan_id = ""
    summaries = _fixture_plan(artifacts_root, fixture_id)
    if summaries is not None:
        plan_id = summaries.plan_id

    total = 0
    completed = 0
    errors = 0
    tables = 0
    manifest_lines: list[str] = []
    if stale:
        for metadata in selected:
            total += 1
            manifest_lines.append(
                canonical_json(
                    {
                        "case_id": metadata.key.case_id,
                        "status": "stale_fixture",
                        "tables": 0,
                    }
                )
            )
    else:
        source = FixtureFilingSource(artifacts_root, fixture_id)
        by_case = {item.key.case_id: item for item in selected}
        done: set[str] = set()
        for metadata in selected:
            if metadata.key.case_id in done:
                continue
            filing_cases = [
                item
                for item in selected
                if item.key.accession == metadata.key.accession
            ]
            try:
                payloads = source.documents_for(metadata.key.accession)
                documents = tuple(
                    DocumentInput(item.document_name, item.result) for item in payloads
                )
                routes = {
                    item.document_name: _route_for(item.result.representation)
                    for item in payloads
                }
                filing = FilingRow(accession=metadata.key.accession, cik=None, form="")
                plan = Plan(
                    plan_id=plan_id,
                    root=Path(),
                    provenance={
                        "source_snapshot_id": (
                            summaries.source_snapshot_id if summaries else ""
                        ),
                        "registry_state": summaries.registry_state if summaries else "",
                        "normalize_version": metadata.stamps.normalize_version,
                        "renderer_version": metadata.stamps.renderer_version,
                    },
                    filings=(filing,),
                    profile_application=(),
                    document_targets=(),
                    work_items=(),
                )
                outputs = classify_products(plan, filing, documents, routes=routes)
                geometry_rows = [dict(row) for row in outputs.geometry_rows]
                classification_rows = [dict(row) for row in outputs.classification_rows]
                for case in filing_cases:
                    done.add(case.key.case_id)
                    total += 1
                    own_geometry = [
                        row
                        for row in geometry_rows
                        if row["source_document"] == case.key.source_document
                    ]
                    own_rows = [
                        row
                        for row in classification_rows
                        if row["source_document"] == case.key.source_document
                    ]
                    payload = {
                        "case_id": case.key.case_id,
                        "plan_id": plan_id,
                        "accession": case.key.accession,
                        "source_document": case.key.source_document,
                        "stamps": case.stamps.as_record(),
                        "geometry_inventory": own_geometry,
                        "classifications": own_rows,
                    }
                    case_dir = paths.case_dir(case.key.case_id)
                    case_dir.mkdir(parents=True, exist_ok=True)
                    atomic_write_json(case_dir / CLASSIFICATIONS_FILE, payload)
                    tables += len(own_rows)
                    completed += 1
                    manifest_lines.append(
                        canonical_json(
                            {
                                "case_id": case.key.case_id,
                                "status": "completed",
                                "tables": len(own_rows),
                                "digest": sha256_text(canonical_json(payload)),
                            }
                        )
                    )
            except Exception as error:  # per-filing isolation, house pattern
                for case in filing_cases:
                    if case.key.case_id in done:
                        continue
                    done.add(case.key.case_id)
                    if case.key.case_id not in by_case:
                        continue
                    total += 1
                    errors += 1
                    manifest_lines.append(
                        canonical_json(
                            {
                                "case_id": case.key.case_id,
                                "status": "execution_error",
                                "tables": 0,
                                "error": f"{type(error).__name__}: {error}",
                            }
                        )
                    )
    summary = ReviewSummary(
        total=total,
        completed=completed,
        stale_fixture=total if stale else 0,
        execution_error=errors,
        tables=tables,
    )
    atomic_write_text(
        paths.manifest_path, "".join(f"{line}\n" for line in manifest_lines)
    )
    atomic_write_json(
        paths.root / SUMMARY_FILE,
        {"review_id": review_id, "fixture_id": fixture_id, **asdict(summary)},
    )
    exit_code = 1 if (stale or errors) else 0
    return ReviewRunResult(
        review_id=review_id,
        output_root=paths.root,
        summary=summary,
        exit_code=exit_code,
    )


def _fixture_plan(artifacts_root: Path | str, fixture_id: str):
    from edgar_sec.pipelines.table_classification.fixture_store.discovery import (
        discover_fixtures,
    )

    for item in discover_fixtures(artifacts_root):
        if item.fixture_id == fixture_id:
            return item.plan_pin
    return None


def read_case_classifications(case_dir: Path) -> list[dict] | None:
    """Read one case's classification rows, or None when absent."""
    path = Path(case_dir) / CLASSIFICATIONS_FILE
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return list(payload.get("classifications") or [])
