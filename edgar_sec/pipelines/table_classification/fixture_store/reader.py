"""Read-only replay access to stored computed products."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

from edgar_sec.engine.forms.normalize import NormalizationResult
from edgar_sec.foundation.hashing import sha256_text
from edgar_sec.foundation.serialization import canonical_json

from ._db import fixture_paths, manifest_details, open_fixture, read_manifest
from .models import (
    FixtureCaseKey,
    FixtureCaseMetadata,
    FixtureStoreError,
    ProductStamps,
)
from .products import deserialize_result


def list_fixture_cases(
    artifacts_root: Path | str, fixture_id: str
) -> tuple[FixtureCaseMetadata, ...]:
    """Enumerate one fixture's cases in stable case order."""
    paths = fixture_paths(artifacts_root, fixture_id)
    _, stamps = manifest_details(read_manifest(paths))
    connection = open_fixture(paths, readonly=True)
    try:
        rows = connection.execute(
            "SELECT accession, source_document, products_sha256 "
            "FROM classification_cases ORDER BY case_id"
        ).fetchall()
    finally:
        connection.close()
    return tuple(
        FixtureCaseMetadata(
            fixture_id=fixture_id,
            key=FixtureCaseKey(accession=row[0], source_document=row[1]),
            stamps=stamps,
            products_sha256=row[2],
        )
        for row in rows
    )


def read_case_products(
    artifacts_root: Path | str, fixture_id: str, case_id: str
) -> tuple[ProductStamps, NormalizationResult]:
    """Replay one case's products as a result, verifying its digest."""
    paths = fixture_paths(artifacts_root, fixture_id)
    _, stamps = manifest_details(read_manifest(paths))
    connection = open_fixture(paths, readonly=True)
    try:
        row = connection.execute(
            "SELECT products_json, products_sha256 FROM classification_cases "
            "WHERE case_id = ?",
            (case_id,),
        ).fetchone()
    finally:
        connection.close()
    if row is None:
        raise FixtureStoreError(f"fixture case is missing: {case_id}")
    products = json.loads(row[0])
    if sha256_text(canonical_json(products)) != row[1]:
        raise FixtureStoreError(f"fixture case digest mismatch: {case_id}")
    return stamps, deserialize_result(products)


def iter_case_results(
    artifacts_root: Path | str, fixture_id: str
) -> Iterator[tuple[FixtureCaseMetadata, NormalizationResult]]:
    """Replay every case in a fixture, in stable case order."""
    for metadata in list_fixture_cases(artifacts_root, fixture_id):
        _, result = read_case_products(artifacts_root, fixture_id, metadata.key.case_id)
        yield metadata, result


def validate_stamps(
    artifacts_root: Path | str, fixture_id: str, expected: ProductStamps
) -> ProductStamps:
    """Return a fixture's stamps, refusing any mismatch with expected."""
    paths = fixture_paths(artifacts_root, fixture_id)
    _, stamps = manifest_details(read_manifest(paths))
    if stamps != expected:
        raise FixtureStoreError(
            f"fixture {fixture_id} is valid for {stamps.as_record()}, "
            f"not {expected.as_record()}; regenerate it"
        )
    return stamps
