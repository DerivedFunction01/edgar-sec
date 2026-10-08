"""Read-only validation of the active published family index."""

from __future__ import annotations

from pathlib import Path

import pyarrow.parquet as pq

from edgar_sec.domain.taxonomy.family_vocab import rule_fingerprint_payload
from edgar_sec.engine.company_family.assignment import ASSIGNMENT_COLUMNS
from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.foundation.serialization import canonical_hash
from edgar_sec.infra.storage.cohort.catalog import CohortCatalog
from edgar_sec.infra.storage.cohort.models import FamilyIndexRecord
from edgar_sec.infra.storage.cohort.operations import FamilyIndexNotFoundError
from edgar_sec.infra.storage.cohort.paths import resolve_cohort_paths


def resolve_active_family_index(
    artifacts_root: Path,
) -> tuple[FamilyIndexRecord, Path]:
    paths = resolve_cohort_paths(artifacts_root)
    catalog = CohortCatalog(paths)
    universe_id = catalog.get_active_source_pointer("cik_lookup")
    if universe_id is None:
        raise FamilyIndexNotFoundError(
            "no published SEC universe; refresh the cohort source and publish its "
            "family index with `cohort family-index`"
        )
    record = catalog.get_active_family_index(universe_id)
    if record is None:
        raise FamilyIndexNotFoundError(
            "no family index is published for active SEC universe "
            f"{universe_id}; run `cohort family-index`"
        )
    if record.universe_cohort_id != universe_id:
        raise FamilyIndexNotFoundError(
            "active family index is stale for the current SEC universe; "
            "run `cohort family-index`"
        )
    if record.rules_fingerprint != canonical_hash(rule_fingerprint_payload()):
        raise FamilyIndexNotFoundError(
            "active family index uses outdated assignment rules; "
            "run `cohort family-index`"
        )
    dataset = paths.resolve_relative_path(record.dataset_path)
    if dataset != paths.family_index_file(record.family_index_id):
        raise FamilyIndexNotFoundError(
            "active family index path does not match its content identifier"
        )
    if not dataset.is_file():
        raise FamilyIndexNotFoundError(
            f"active family index dataset is missing: {record.family_index_id}"
        )
    if file_sha256(dataset) != record.dataset_sha256:
        raise FamilyIndexNotFoundError(
            f"active family index dataset digest mismatch: {record.family_index_id}"
        )
    try:
        schema_names = set(pq.read_schema(dataset).names)
    except (OSError, ValueError) as error:
        raise FamilyIndexNotFoundError(
            f"active family index is unreadable: {record.family_index_id}"
        ) from error
    if not set(ASSIGNMENT_COLUMNS) <= schema_names:
        raise FamilyIndexNotFoundError(
            "active family index has an incompatible Parquet schema: "
            f"{record.family_index_id}"
        )
    return record, dataset


__all__ = ["resolve_active_family_index"]
