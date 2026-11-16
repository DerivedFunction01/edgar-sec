"""Capture computed products into a plan-pinned fixture."""

from __future__ import annotations

from pathlib import Path

from edgar_sec.engine.forms.normalize import NormalizationResult
from edgar_sec.foundation.hashing import sha256_text
from edgar_sec.foundation.serialization import canonical_json

from ._db import (
    fixture_paths,
    manifest_details,
    now_iso,
    open_fixture,
    read_manifest,
    write_manifest,
)
from .models import (
    CaptureResult,
    CapturedCase,
    FixtureCaseKey,
    FixtureOperationError,
    FixtureStoreError,
    PlanPin,
    ProductStamps,
)
from .products import serialize_result


def capture_cases(
    artifacts_root: Path | str,
    fixture_id: str,
    plan_pin: PlanPin,
    cases: tuple[CapturedCase, ...],
) -> CaptureResult:
    """Store captured cases, reusing identical stored products."""
    if not cases:
        raise FixtureOperationError("capture requires at least one case")
    stamps = cases[0].stamps
    if any(case.stamps != stamps for case in cases):
        raise FixtureOperationError("one fixture carries one set of product stamps")
    paths = fixture_paths(artifacts_root, fixture_id)
    created_at = now_iso()
    if paths.manifest_path.exists():
        envelope = read_manifest(paths)
        created_at = envelope.created_at
        stored_pin, stored_stamps = manifest_details(envelope)
        if stored_pin != plan_pin:
            raise FixtureStoreError("fixture is pinned to a different plan")
        if stored_stamps != stamps:
            raise FixtureStoreError("fixture carries different product stamps")
    added = 0
    reused = 0
    connection = open_fixture(paths)
    try:
        for case in cases:
            payload = canonical_json(case.products)
            digest = sha256_text(payload)
            row = connection.execute(
                "SELECT products_sha256 FROM classification_cases WHERE case_id = ?",
                (case.key.case_id,),
            ).fetchone()
            if row is not None:
                if row[0] != digest:
                    raise FixtureStoreError(
                        f"case {case.key.case_id} already stores different products"
                    )
                reused += 1
                continue
            connection.execute(
                "INSERT INTO classification_cases VALUES (?, ?, ?, ?, ?)",
                (
                    case.key.case_id,
                    case.key.accession,
                    case.key.source_document,
                    payload,
                    digest,
                ),
            )
            added += 1
        connection.commit()
        count = int(
            connection.execute("SELECT COUNT(*) FROM classification_cases").fetchone()[
                0
            ]
        )
    finally:
        connection.close()
    write_manifest(
        paths, plan_pin=plan_pin, stamps=stamps, case_count=count, created_at=created_at
    )
    return CaptureResult(fixture_id=fixture_id, cases_added=added, cases_reused=reused)


def capture_results(
    artifacts_root: Path | str,
    fixture_id: str,
    plan_pin: PlanPin,
    items: tuple[tuple[str, str, NormalizationResult, ProductStamps], ...],
) -> CaptureResult:
    """Capture live results given as (accession, document, result, stamps)."""
    cases = tuple(
        CapturedCase(
            key=FixtureCaseKey(accession=accession, source_document=source_document),
            stamps=stamps,
            products=serialize_result(result),
        )
        for accession, source_document, result, stamps in items
    )
    return capture_cases(artifacts_root, fixture_id, plan_pin, cases)
