"""Build and reuse the published company-family assignment for one universe cohort.

Derived from the compiled full roster rather than the catalog profile corpus, and
content-addressed on that roster plus the rules that produced it, so a roster or word
list change publishes a new artifact and leaves the previous one valid.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import duckdb

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
from edgar_sec.infra.storage.atomic import atomic_write_json
from edgar_sec.infra.storage.duckdb import connect, sql_literal
from edgar_sec.infra.storage.cohort.catalog import CohortCatalog
from edgar_sec.infra.storage.cohort.paths import resolve_cohort_paths
from edgar_sec.infra.storage.cohort.sources import resolve_active_source

from .cohort_adapter import cohort_record_to_roster
from .paths import (
    FAMILY_INDEX_MANIFEST_KIND,
    FAMILY_INDEX_MANIFEST_NAME,
    MetadataPaths,
    resolve_metadata_paths,
)

__all__ = [
    "FamilyIndexArtifact",
    "build_family_index",
    "ensure_family_index",
    "family_index_id",
    "published_universe_roster",
]


@dataclass(frozen=True, slots=True)
class FamilyIndexArtifact:
    """One published assignment, with the path a downstream join reads."""

    family_index_id: str
    assignment_path: Path
    manifest_path: Path


def family_index_id(*, roster_id: str, dataset_sha256: str) -> str:
    """Content identity of an assignment: the roster it came from plus the rules."""
    payload = {
        "kind": FAMILY_INDEX_MANIFEST_KIND,
        "schema_version": FAMILY_INDEX_SCHEMA_VERSION,
        "roster_id": roster_id,
        "dataset_sha256": dataset_sha256,
        "rules": canonical_hash(rule_fingerprint_payload()),
    }
    return canonical_hash(payload)[:32]


def published_universe_roster(
    paths: MetadataPaths | None = None,
) -> tuple[Path, str, str]:
    """Return the published universe cohort's dataset path, roster id, and sha256.

    Raises when the universe is unpublished, because an assignment built from a narrower
    corpus would encode that corpus's vocabulary as corporate identity.
    """
    metadata_paths = paths or resolve_metadata_paths()
    cohort_paths = resolve_cohort_paths(metadata_paths.artifacts_root)
    record = resolve_active_source("cik_lookup", catalog=CohortCatalog(cohort_paths))
    if record is None:
        raise FileNotFoundError(
            "no published cik_lookup cohort; refresh the metadata universe "
            "before building a company-family assignment"
        )
    roster = cohort_record_to_roster(record, cohort_paths)
    if roster.dataset is None:
        raise FileNotFoundError("active cik_lookup cohort has no dataset")
    return roster.dataset, roster.roster_id, record.dataset_sha256


def _roster_relation(dataset: Path) -> str:
    return (
        "SELECT lpad(CAST(cik_padded AS VARCHAR), 10, '0') AS cik, "
        f"name FROM read_parquet({sql_literal(str(dataset))})"
    )


_ASSIGNMENT_PROJECTION = ", ".join(ASSIGNMENT_COLUMNS)

_REFERENCED_ASSIGNMENT = (
    "SELECT " + _ASSIGNMENT_PROJECTION + " FROM family_assignment ORDER BY cik"
)


def _copy_assignment_sql(staging: Path) -> str:
    """The COPY statement publishing one sorted row per registrant."""
    return f"COPY ({_REFERENCED_ASSIGNMENT}) TO {sql_literal(str(staging))} (FORMAT PARQUET)"


def _write_manifest(
    manifest_path: Path,
    *,
    family_index_id: str,
    roster_id: str,
    dataset_sha256: str,
    assignment_sha256: str,
    stats: FamilyAssignmentStats,
) -> None:
    atomic_write_json(
        manifest_path,
        {
            "manifest_kind": FAMILY_INDEX_MANIFEST_KIND,
            "family_index_id": family_index_id,
            "schema_version": FAMILY_INDEX_SCHEMA_VERSION,
            "roster_id": roster_id,
            "dataset_sha256": dataset_sha256,
            "assignment_sha256": assignment_sha256,
            "rules_fingerprint": canonical_hash(rule_fingerprint_payload()),
            "registrants": stats.registrants,
            "entity_families": stats.entity_families,
            "spv_families": stats.spv_families,
            "singletons": stats.singletons,
            "spv_registrants": stats.spv_registrants,
            "unresolved_sponsors": stats.unresolved_sponsors,
        },
    )


def _reusable(
    manifest_path: Path, assignment_path: Path, expected_id: str, expected_sha: str
) -> bool:
    """Report whether a published assignment still matches its recorded inputs.

    The payload checksum is re-verified rather than trusted from the manifest, because a
    truncated or half-written Parquet file would otherwise pass as a cache hit.
    """
    if not manifest_path.is_file() or not assignment_path.is_file():
        return False
    try:
        recorded = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if recorded.get("manifest_kind") != FAMILY_INDEX_MANIFEST_KIND:
        return False
    if recorded.get("family_index_id") != expected_id:
        return False
    if recorded.get("dataset_sha256") != expected_sha:
        return False
    return recorded.get("assignment_sha256") == file_sha256(assignment_path)


def build_family_index(
    *,
    dataset: Path,
    roster_id: str,
    dataset_sha256: str,
    output_path: Path,
    manifest_path: Path,
) -> FamilyIndexArtifact:
    """Assign families for one roster dataset and publish the artifact atomically."""
    index_id = family_index_id(roster_id=roster_id, dataset_sha256=dataset_sha256)
    staging = output_path.with_name(output_path.name + ".staging")
    staging.parent.mkdir(parents=True, exist_ok=True)
    staging.unlink(missing_ok=True)

    with connect() as con:
        stats = build_assignment(con, _roster_relation(dataset))
        con.execute(_copy_assignment_sql(staging))
    staging.replace(output_path)

    _write_manifest(
        manifest_path,
        family_index_id=index_id,
        roster_id=roster_id,
        dataset_sha256=dataset_sha256,
        assignment_sha256=file_sha256(output_path),
        stats=stats,
    )
    return FamilyIndexArtifact(index_id, output_path, manifest_path)


def ensure_family_index(paths: MetadataPaths | None = None) -> FamilyIndexArtifact:
    """Return a verified assignment for the published universe, building if needed."""
    metadata_paths = paths or resolve_metadata_paths()
    dataset, roster_id, dataset_sha256 = published_universe_roster(metadata_paths)
    index_id = family_index_id(roster_id=roster_id, dataset_sha256=dataset_sha256)
    output_path = metadata_paths.family_index_file(index_id)
    manifest_path = metadata_paths.family_index_manifest(index_id)
    if _reusable(manifest_path, output_path, index_id, dataset_sha256):
        return FamilyIndexArtifact(index_id, output_path, manifest_path)
    return build_family_index(
        dataset=dataset,
        roster_id=roster_id,
        dataset_sha256=dataset_sha256,
        output_path=output_path,
        manifest_path=manifest_path,
    )
