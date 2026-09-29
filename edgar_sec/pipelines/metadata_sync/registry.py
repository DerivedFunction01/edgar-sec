"""Curated-versus-source CIK registry and effective-input projections.

``compare_sources`` answers the question the fetch pipeline cannot: which
registrants exist upstream that a curated CIK input does not cover. It is a pure
projection — it reads an already published source snapshot and a curated CSV and
performs no network access, so a comparison is reproducible from immutable inputs.

The output contract is the one v1 established, because the projections are
consumed by the existing CSV-driven augmentation path:

* ``listing_observations`` — every normalized upstream listing.
* ``registrant_registry`` — one row per CIK in the union of curated and active.
* ``new_ciks`` — the subset the curated input does not cover.
* ``augmentation_worklist`` — the new CIKs shaped for an augmentation run.
* ``effective_ciks`` — the full union as a CIK roster dataset, the carrier a plan
  consumes.
* ``effective_cik_input.csv`` — the same union as a CIK manifest, retained as an
  export for people and v1-era scripts.

Every Parquet dataset is published beside a manifest carrying its content digest
and upstream chain, so a consumer can prove which source snapshot and curated
input produced it. The registry identity is content-derived from those two
inputs, so an unchanged comparison is a no-op rather than a new artifact.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import pyarrow as pa

from edgar_sec.foundation.hashing import file_sha256, sha256_bytes
from edgar_sec.foundation.runtime.settings.runtime import DEFAULT_CHUNK_SIZE
from edgar_sec.foundation.serialization import canonical_json
from edgar_sec.infra.storage.atomic import atomic_write_json, atomic_write_text
from edgar_sec.infra.storage.parquet import (
    DEFAULT_ROW_GROUP_SIZE,
    read_parquet_schema,
    write_parquet_table,
)

from .manifest import read_cik_manifest
from .paths import REGISTRY_EFFECTIVE_CIK_DATASET, MetadataPaths
from .roster import (
    ROSTER_SCHEMA_VERSION,
    Roster,
    RosterError,
    build_roster,
    read_roster,
    roster_from_manifest,
    roster_to_csv_text,
    write_roster,
)
from .source_registry import SOURCE_NAME, load_source_snapshot, parse_company_tickers

REGISTRY_SCHEMA_VERSION = "1.0.0"
REGISTRY_MANIFEST_KIND = "registry_artifact"
EFFECTIVE_INPUT_MANIFEST_KIND = "effective_cik_input"
ROSTER_MANIFEST_KIND = "effective_cik_roster"

LISTING_SCHEMA = pa.schema(
    [
        ("source_key", pa.string()),
        ("cik_padded", pa.string()),
        ("ticker", pa.string()),
        ("title", pa.string()),
        ("source_snapshot_id", pa.string()),
        ("observed_at", pa.string()),
    ]
)

REGISTRY_SCHEMA = pa.schema(
    [
        ("cik_padded", pa.string()),
        ("canonical_name", pa.string()),
        ("curated_name", pa.string()),
        ("active_title", pa.string()),
        ("tickers", pa.list_(pa.string())),
        ("source_snapshot_ids", pa.list_(pa.string())),
        ("curated_membership", pa.bool_()),
        ("active_listing_membership", pa.bool_()),
        ("historical_retained", pa.bool_()),
        ("processing_eligible", pa.bool_()),
        ("activity_class", pa.string()),
        ("refresh_cadence", pa.string()),
    ]
)

WORKLIST_SCHEMA = pa.schema(
    [
        ("cik_padded", pa.string()),
        ("name", pa.string()),
        ("source_row", pa.int64()),
        ("work_reason", pa.string()),
        ("source_snapshot_id", pa.string()),
        ("base_metadata_manifest_id", pa.string()),
    ]
)

__all__ = [
    "EFFECTIVE_INPUT_MANIFEST_KIND",
    "LISTING_SCHEMA",
    "REGISTRY_MANIFEST_KIND",
    "REGISTRY_SCHEMA",
    "REGISTRY_SCHEMA_VERSION",
    "ROSTER_MANIFEST_KIND",
    "WORKLIST_SCHEMA",
    "RegistryError",
    "compare_sources",
    "load_registry_manifest",
    "load_registry_roster",
    "registry_id_for",
]


class RegistryError(ValueError):
    """Raised when a curated/source comparison cannot be produced or validated."""


def registry_id_for(source_snapshot_id: str, curated_fingerprint: str) -> str:
    """Content-derived registry identity for one source/curated-input pair."""
    material = canonical_json(
        [
            "registrant-registry-v1",
            REGISTRY_SCHEMA_VERSION,
            source_snapshot_id,
            curated_fingerprint,
        ]
    ).encode("utf-8")
    return sha256_bytes(material)[:32]


def _write_dataset(
    rows: list[dict[str, Any]],
    schema: pa.Schema,
    path: Path,
) -> int:
    """Write one registry Parquet dataset atomically and read it back."""
    table = pa.Table.from_pylist(rows, schema=schema)
    write_parquet_table(table, path)
    written = read_parquet_schema(path)
    if not written.equals(schema, check_metadata=False):
        raise RegistryError(f"registry dataset schema drifted: {path}")
    return table.num_rows


def _publish_dataset_manifest(
    *,
    path: Path,
    dataset: str,
    registry_id: str,
    root: Path,
    row_count: int,
    upstream: tuple[str, ...],
    source_snapshot_id: str,
) -> dict[str, Any]:
    """Write the manifest describing one published registry dataset."""
    manifest = {
        "manifest_kind": REGISTRY_MANIFEST_KIND,
        "manifest_schema_version": REGISTRY_SCHEMA_VERSION,
        "dataset": dataset,
        "producer_phase": "metadata",
        "registry_id": registry_id,
        "schema_version": REGISTRY_SCHEMA_VERSION,
        "source_snapshot_id": source_snapshot_id,
        "artifact_path": path.relative_to(root).as_posix(),
        "storage_format": "parquet",
        "byte_count": path.stat().st_size,
        "artifact_sha256": file_sha256(path),
        "row_group_size": DEFAULT_ROW_GROUP_SIZE,
        "row_count": row_count,
        "upstream_artifact_ids": list(upstream),
    }
    atomic_write_json(
        path.with_name(path.name + ".manifest.json"),
        manifest,
        canonical=False,
        indent=2,
    )
    return manifest


def _build_registry_rows(
    curated_by_cik: dict[str, str],
    active_by_cik: dict[str, list[dict[str, Any]]],
    source_snapshot_id: str,
) -> list[dict[str, Any]]:
    """Build one registry row per CIK in the union of curated and active sets."""
    rows: list[dict[str, Any]] = []
    for cik in sorted(set(curated_by_cik) | set(active_by_cik)):
        curated_name = curated_by_cik.get(cik, "")
        active = sorted(
            active_by_cik.get(cik, []), key=lambda row: (row["ticker"], row["title"])
        )
        active_title = active[0]["title"] if active else ""
        rows.append(
            {
                "cik_padded": cik,
                "canonical_name": curated_name or active_title,
                "curated_name": curated_name,
                "active_title": active_title,
                "tickers": sorted({row["ticker"] for row in active if row["ticker"]}),
                "source_snapshot_ids": [source_snapshot_id] if active else [],
                "curated_membership": cik in curated_by_cik,
                "active_listing_membership": bool(active),
                "historical_retained": True,
                "processing_eligible": True,
                "activity_class": "active_listing" if active else "curated_only",
                "refresh_cadence": "quarterly" if active else "unknown",
            }
        )
    return rows


def compare_sources(
    *,
    curated_input_path: str | Path,
    source_manifest_path: str | Path,
    metadata_paths: MetadataPaths,
) -> dict[str, Any]:
    """Project the curated CIK input against a published source snapshot.

    Reads only immutable inputs: the verified source snapshot named by
    ``source_manifest_path`` and the curated CSV. No network access is performed,
    so the result is a pure function of those two files.
    """
    source = load_source_snapshot(source_manifest_path)
    source_snapshot_id = str(source.manifest["snapshot_id"])
    listings, _parse_report = parse_company_tickers(
        source.raw_path.read_bytes(),
        snapshot_id=source_snapshot_id,
        observed_at=str(source.manifest["retrieved_at"]),
    )

    manifest = read_cik_manifest(curated_input_path)
    curated_roster = roster_from_manifest(manifest)
    curated_by_cik = curated_roster.name_map()
    active_by_cik: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for listing in listings:
        active_by_cik[listing["cik_padded"]].append(listing)

    registry_rows = _build_registry_rows(
        curated_by_cik, active_by_cik, source_snapshot_id
    )
    delta_rows = [row for row in registry_rows if not row["curated_membership"]]
    worklist_rows = [
        {
            "cik_padded": row["cik_padded"],
            "name": row["canonical_name"],
            "source_row": 0,
            "work_reason": "active_source_only",
            "source_snapshot_id": source_snapshot_id,
            "base_metadata_manifest_id": "",
        }
        for row in delta_rows
    ]

    registry_id = registry_id_for(source_snapshot_id, manifest.input_fingerprint)
    root = metadata_paths.registry_root(registry_id)
    datasets_root = metadata_paths.registry_manifest_root(registry_id)
    root.mkdir(parents=True, exist_ok=True)
    datasets_root.mkdir(parents=True, exist_ok=True)
    artifacts_root = metadata_paths.metadata_root

    published: dict[str, dict[str, Any]] = {}
    upstream = (source_snapshot_id,)
    for dataset, rows, schema in (
        ("listing_observations", listings, LISTING_SCHEMA),
        ("registrant_registry", registry_rows, REGISTRY_SCHEMA),
        ("new_ciks", delta_rows, REGISTRY_SCHEMA),
        ("augmentation_worklist", worklist_rows, WORKLIST_SCHEMA),
    ):
        path = metadata_paths.registry_dataset(registry_id, dataset)
        row_count = _write_dataset(rows, schema, path)
        published[dataset] = _publish_dataset_manifest(
            path=path,
            dataset=dataset,
            registry_id=registry_id,
            root=artifacts_root,
            row_count=row_count,
            upstream=upstream,
            source_snapshot_id=source_snapshot_id,
        )

    effective_roster = _publish_effective_roster(
        registry_id, registry_rows, metadata_paths, artifacts_root
    )
    effective_csv = metadata_paths.effective_input_file(registry_id)
    atomic_write_text(effective_csv, roster_to_csv_text(effective_roster))
    effective_manifest = {
        "manifest_kind": EFFECTIVE_INPUT_MANIFEST_KIND,
        "manifest_schema_version": REGISTRY_SCHEMA_VERSION,
        "registry_id": registry_id,
        "source": SOURCE_NAME,
        "source_snapshot_id": source_snapshot_id,
        "curated_input_path": str(manifest.input_path),
        "curated_input_fingerprint": manifest.input_fingerprint,
        "artifact_path": effective_csv.relative_to(artifacts_root).as_posix(),
        "artifact_sha256": file_sha256(effective_csv),
        "row_count": len(registry_rows),
        "roster_id": effective_roster.roster_id,
        "columns": ["cik", "name"],
        "chunk_size_default": DEFAULT_CHUNK_SIZE,
        "validation_status": "ok",
    }
    atomic_write_json(
        effective_csv.with_name(effective_csv.name + ".manifest.json"),
        effective_manifest,
        canonical=False,
        indent=2,
    )

    return {
        "registry_id": registry_id,
        "source": SOURCE_NAME,
        "source_snapshot_id": source_snapshot_id,
        "curated_input_path": str(manifest.input_path),
        "curated_input_fingerprint": manifest.input_fingerprint,
        "registry_root": str(root),
        "datasets_root": str(datasets_root),
        "effective_input_path": str(effective_csv),
        "effective_roster_path": str(metadata_paths.effective_cik_roster(registry_id)),
        "roster_id": effective_roster.roster_id,
        "curated_cik_count": len(curated_by_cik),
        "active_cik_count": len(active_by_cik),
        "registry_row_count": len(registry_rows),
        "new_cik_count": len(delta_rows),
        "listing_row_count": len(listings),
        "artifact_sha256": {
            dataset: manifest_["artifact_sha256"]
            for dataset, manifest_ in published.items()
        },
        "validation_status": "ok",
    }


def _publish_effective_roster(
    registry_id: str,
    registry_rows: list[dict[str, Any]],
    metadata_paths: MetadataPaths,
    artifacts_root: Path,
) -> Roster:
    """Publish the effective CIK roster a plan consumes, with its manifest.

    This is the artifact that replaces the CSV as the internal carrier: the CSV
    is still written beside it, but nothing in the fetch path has to parse a
    text manifest to learn which CIKs a run covers.
    """
    try:
        roster = build_roster(
            [str(row["cik_padded"]) for row in registry_rows],
            [str(row["canonical_name"] or "") for row in registry_rows],
        )
    except RosterError as exc:
        raise RegistryError(f"effective CIK roster is not publishable: {exc}") from exc
    path = metadata_paths.effective_cik_roster(registry_id)
    digest = write_roster(roster, path)
    atomic_write_json(
        path.with_name(path.name + ".manifest.json"),
        {
            "manifest_kind": ROSTER_MANIFEST_KIND,
            "manifest_schema_version": ROSTER_SCHEMA_VERSION,
            "dataset": REGISTRY_EFFECTIVE_CIK_DATASET,
            "producer_phase": "metadata",
            "registry_id": registry_id,
            "roster_id": roster.roster_id,
            "artifact_path": path.relative_to(artifacts_root).as_posix(),
            "storage_format": "parquet",
            "artifact_sha256": digest,
            "row_count": roster.row_count,
            "upstream_artifact_ids": [registry_id],
        },
        canonical=False,
        indent=2,
    )
    return roster


def load_registry_roster(registry_id: str, metadata_paths: MetadataPaths) -> Roster:
    """Load one registry's effective CIK roster, verifying its published digest.

    The manifest is the trust boundary: a roster swapped after publication is
    refused, so a plan built from it provably covers the cohort the comparison
    actually published.
    """
    path = metadata_paths.effective_cik_roster(registry_id)
    manifest_path = path.with_name(path.name + ".manifest.json")
    if not manifest_path.is_file():
        raise FileNotFoundError(f"registry roster manifest not found: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if file_sha256(path) != manifest.get("artifact_sha256"):
        raise RegistryError("effective CIK roster digest does not match its manifest")

    return read_roster(path, expected_roster_id=str(manifest.get("roster_id", "")))


def load_registry_manifest(
    registry_id: str, metadata_paths: MetadataPaths
) -> dict[str, Any]:
    """Load one registry's effective-input manifest and verify its CSV digest.

    Retained for the CSV export contract. A plan consumes the roster dataset via
    :func:`load_registry_roster`; this reads the human-facing manifest beside it.
    """
    path = metadata_paths.effective_input_file(registry_id).with_name(
        "effective_cik_input.csv.manifest.json"
    )
    if not path.is_file():
        raise FileNotFoundError(f"registry manifest not found: {path}")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    csv_path = Path(manifest["artifact_path"])
    if not csv_path.is_absolute():
        csv_path = metadata_paths.metadata_root / csv_path
    if file_sha256(csv_path) != manifest.get("artifact_sha256"):
        raise RegistryError("effective CIK input digest does not match its manifest")
    return manifest
