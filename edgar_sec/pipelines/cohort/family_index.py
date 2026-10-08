"""Publish the company-family assignment for the active universe cohort."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from edgar_sec.domain.taxonomy.family_vocab import (
    FAMILY_INDEX_SCHEMA_VERSION,
    rule_fingerprint_payload,
)
from edgar_sec.engine.company_family.assignment import (
    ASSIGNMENT_COLUMNS,
    FamilyAssignmentStats,
    build_assignment,
)
from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.foundation.serialization import canonical_hash
from edgar_sec.infra.storage.cohort.catalog import CohortCatalog
from edgar_sec.infra.storage.cohort.models import FamilyIndexRecord
from edgar_sec.infra.storage.cohort.paths import CohortPaths
from edgar_sec.infra.storage.cohort.sources import resolve_active_source
from edgar_sec.infra.storage.duckdb import connect, copy_query_to_parquet, sql_literal

_INDEX_KIND = "company_family_index"


@dataclass(frozen=True, slots=True)
class FamilyIndexArtifact:
    record: FamilyIndexRecord
    dataset_path: Path


def _family_index_id(roster_id: str, dataset_sha256: str, rules: str) -> str:
    return canonical_hash(
        {
            "kind": _INDEX_KIND,
            "schema_version": FAMILY_INDEX_SCHEMA_VERSION,
            "roster_id": roster_id,
            "dataset_sha256": dataset_sha256,
            "rules": rules,
        }
    )[:32]


def _roster_relation(dataset: Path) -> str:
    return (
        "SELECT lpad(CAST(cik_padded AS VARCHAR), 10, '0') AS cik, name "
        f"FROM read_parquet({sql_literal(str(dataset))})"
    )


def _assignment_query() -> str:
    return f"SELECT {', '.join(ASSIGNMENT_COLUMNS)} FROM family_assignment ORDER BY cik"


def _assignment_stats(dataset: Path) -> FamilyAssignmentStats:
    path = sql_literal(str(dataset))
    with connect() as con:
        values = con.execute(
            f"""
            SELECT count(*),
                   count(DISTINCT company_family) FILTER (WHERE family_kind = 'entity'),
                   count(DISTINCT company_family) FILTER (WHERE family_kind = 'spv'),
                   count(*) FILTER (WHERE family_kind = 'singleton'),
                   count(*) FILTER (WHERE family_kind = 'spv'),
                   count(*) FILTER (
                       WHERE family_kind = 'spv' AND (sponsor_key IS NULL OR sponsor_key = '')
                   )
            FROM read_parquet({path})
            """
        ).fetchone()
    return FamilyAssignmentStats(*(int(value or 0) for value in values))


def _reuse_active(
    *,
    active: FamilyIndexRecord,
    universe_cohort_id: str,
    family_index_id: str,
    rules_fingerprint: str,
    expected_path: str,
    dataset_path: Path,
) -> tuple[FamilyIndexArtifact, FamilyAssignmentStats]:
    if (
        active.universe_cohort_id != universe_cohort_id
        or active.family_index_id != family_index_id
        or active.rules_fingerprint != rules_fingerprint
        or active.dataset_path != expected_path
    ):
        raise ValueError("active family index metadata does not match its content id")
    if not dataset_path.is_file() or file_sha256(dataset_path) != active.dataset_sha256:
        raise ValueError("active family index dataset is missing or corrupt")
    if {entry.name for entry in dataset_path.parent.iterdir()} != {dataset_path.name}:
        raise ValueError("active family index directory contains unexpected files")
    return (
        FamilyIndexArtifact(active, dataset_path),
        _assignment_stats(dataset_path),
    )


def publish_family_index(
    *, catalog: CohortCatalog, paths: CohortPaths
) -> tuple[FamilyIndexArtifact, FamilyAssignmentStats]:
    source = resolve_active_source("cik_lookup", catalog=catalog)
    if source is None:
        raise FileNotFoundError("no active cik_lookup cohort is published")
    universe_dataset = paths.resolve_relative_path(source.dataset_path)
    if not universe_dataset.is_file():
        raise FileNotFoundError(universe_dataset)
    if file_sha256(universe_dataset) != source.dataset_sha256:
        raise ValueError("active cik_lookup dataset digest does not match its record")

    rules_fingerprint = canonical_hash(rule_fingerprint_payload())
    index_id = _family_index_id(
        source.roster_id, source.dataset_sha256, rules_fingerprint
    )
    output_path = paths.family_index_file(index_id)
    relative_path = paths.relative_path(output_path)
    active = catalog.get_active_family_index(source.cohort_id)
    if active is not None and active.family_index_id == index_id:
        return _reuse_active(
            active=active,
            universe_cohort_id=source.cohort_id,
            family_index_id=index_id,
            rules_fingerprint=rules_fingerprint,
            expected_path=relative_path,
            dataset_path=output_path,
        )
    if active is not None and active.dataset_path == relative_path:
        raise ValueError("active family index points at a different content id")

    output_dir = paths.family_index_dir(index_id)
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    try:
        output_dir.mkdir()
    except FileExistsError:
        active = catalog.get_active_family_index(source.cohort_id)
        if active is None or active.family_index_id != index_id:
            raise
        return _reuse_active(
            active=active,
            universe_cohort_id=source.cohort_id,
            family_index_id=index_id,
            rules_fingerprint=rules_fingerprint,
            expected_path=relative_path,
            dataset_path=output_path,
        )
    with connect() as con:
        stats = build_assignment(con, _roster_relation(universe_dataset))
        copy_query_to_parquet(con, _assignment_query(), output_path)
    assignment_sha256 = file_sha256(output_path)
    catalog.set_active_family_index(
        source.cohort_id,
        index_id,
        rules_fingerprint,
        assignment_sha256,
    )

    record = catalog.get_active_family_index(source.cohort_id)
    if record is None:
        raise RuntimeError("family index registration did not persist")
    return FamilyIndexArtifact(record, output_path), stats


__all__ = ["FamilyIndexArtifact", "publish_family_index"]
