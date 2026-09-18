"""Derived CIK registry and effective-input projections."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from defs.runtime.artifacts import artifact_id
from defs.storage import (
    atomic_write_json,
    atomic_write_text,
    file_sha256,
    pa,
    write_table_atomic,
)

from .input_manifest import TargetRow, read_input_manifest
from .source_registry import (
    LISTING_SCHEMA,
    REGISTRY_SCHEMA,
    REGISTRY_SCHEMA_VERSION,
    WORKLIST_SCHEMA,
    load_source_snapshot,
    parse_company_tickers,
)


def _registry_id(source_snapshot_id: str, curated_fingerprint: str) -> str:
    import hashlib

    from defs.storage import canonical_json

    payload = [
        "registrant-registry-v1",
        REGISTRY_SCHEMA_VERSION,
        source_snapshot_id,
        curated_fingerprint,
    ]
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()[:32]


def _publish_parquet_manifest(
    *,
    path: Path,
    dataset: str,
    registry_id: str,
    root: Path,
    row_count: int,
    upstream: tuple[str, ...],
) -> dict:
    digest = file_sha256(path)
    manifest = {
        "manifest_kind": "registry_artifact",
        "manifest_schema_version": REGISTRY_SCHEMA_VERSION,
        "artifact_id": artifact_id(
            dataset=dataset,
            phase="metadata",
            schema_version=REGISTRY_SCHEMA_VERSION,
            artifact_sha256=digest,
        ),
        "dataset": dataset,
        "producer_phase": "metadata",
        "run_id": registry_id,
        "schema_version": REGISTRY_SCHEMA_VERSION,
        "artifact_path": path.relative_to(root).as_posix(),
        "storage_format": "parquet",
        "byte_count": path.stat().st_size,
        "artifact_sha256": digest,
        "row_count": row_count,
        "upstream_artifact_ids": list(upstream),
        "provenance": {"source": "company_tickers_registry"},
    }
    atomic_write_json(
        path.with_name(path.name + ".manifest.json"), manifest, indent=None
    )
    return manifest


def compare_sources(
    *,
    curated_input_path: str | Path,
    source_manifest_path: str | Path,
    artifacts_root: str | Path,
) -> dict:
    """Build registry, effective CSV, and CIK difference artifacts."""
    root = Path(artifacts_root).resolve()
    source = load_source_snapshot(source_manifest_path, artifacts_root=root)
    listings, parse_report = parse_company_tickers(
        source.raw_path.read_bytes(),
        snapshot_id=source.manifest["snapshot_id"],
        observed_at=source.manifest["retrieved_at"],
    )
    curated_rows, curated_report = read_input_manifest(str(curated_input_path))
    curated_by_cik: dict[str, TargetRow] = {row.cik_padded: row for row in curated_rows}
    active_by_cik: dict[str, list[dict]] = defaultdict(list)
    for listing in listings:
        active_by_cik[listing["cik_padded"]].append(listing)
    all_ciks = sorted(set(curated_by_cik) | set(active_by_cik))
    registry_rows: list[dict] = []
    for cik in all_ciks:
        curated = curated_by_cik.get(cik)
        active = sorted(
            active_by_cik.get(cik, []), key=lambda row: (row["ticker"], row["title"])
        )
        curated_name = curated.name if curated is not None else ""
        active_title = active[0]["title"] if active else ""
        registry_rows.append(
            {
                "cik_padded": cik,
                "canonical_name": curated_name or active_title,
                "curated_name": curated_name,
                "active_title": active_title,
                "tickers": sorted({row["ticker"] for row in active if row["ticker"]}),
                "source_snapshot_ids": [source.manifest["snapshot_id"]]
                if active
                else [],
                "curated_membership": curated is not None,
                "active_listing_membership": bool(active),
                "historical_retained": True,
                "processing_eligible": True,
                "activity_class": "active_listing" if active else "curated_only",
                "refresh_cadence": "quarterly" if active else "unknown",
            }
        )
    registry_id = _registry_id(
        source.manifest["snapshot_id"], curated_report["fingerprint"]
    )
    from .paths import resolve_metadata_paths

    metadata_paths = resolve_metadata_paths(env={"ARTIFACTS_ROOT": str(root)})
    registry_root = metadata_paths.registry_snapshot_root(registry_id)
    registry_manifest_root = metadata_paths.registry_manifest_root(registry_id)
    registry_root.mkdir(parents=True, exist_ok=True)
    registry_manifest_root.mkdir(parents=True, exist_ok=True)
    listing_path = registry_manifest_root / "listing_observations.parquet"
    registry_path = registry_manifest_root / "registrant_registry.parquet"
    delta_path = registry_manifest_root / "new_ciks.parquet"
    worklist_path = registry_manifest_root / "augmentation_worklist.parquet"
    delta_rows = [row for row in registry_rows if not row["curated_membership"]]
    worklist_rows = [
        {
            "cik_padded": row["cik_padded"],
            "name": row["canonical_name"],
            "source_row": 0,
            "work_reason": "active_source_only",
            "source_snapshot_id": source.manifest["snapshot_id"],
            "base_metadata_manifest_id": "",
        }
        for row in delta_rows
    ]
    write_table_atomic(
        pa.Table.from_pylist(listings, schema=LISTING_SCHEMA),
        listing_path,
        expected_rows=len(listings),
        expected_schema=LISTING_SCHEMA,
    )
    write_table_atomic(
        pa.Table.from_pylist(registry_rows, schema=REGISTRY_SCHEMA),
        registry_path,
        expected_rows=len(registry_rows),
        expected_schema=REGISTRY_SCHEMA,
    )
    write_table_atomic(
        pa.Table.from_pylist(delta_rows, schema=REGISTRY_SCHEMA),
        delta_path,
        expected_rows=len(delta_rows),
        expected_schema=REGISTRY_SCHEMA,
    )
    write_table_atomic(
        pa.Table.from_pylist(worklist_rows, schema=WORKLIST_SCHEMA),
        worklist_path,
        expected_rows=len(worklist_rows),
        expected_schema=WORKLIST_SCHEMA,
    )
    upstream = (source.manifest["snapshot_id"],)
    listing_manifest = _publish_parquet_manifest(
        path=listing_path,
        dataset="listing_observations",
        registry_id=registry_id,
        root=root,
        row_count=len(listings),
        upstream=upstream,
    )
    registry_manifest = _publish_parquet_manifest(
        path=registry_path,
        dataset="registrant_registry",
        registry_id=registry_id,
        root=root,
        row_count=len(registry_rows),
        upstream=upstream,
    )
    delta_manifest = _publish_parquet_manifest(
        path=delta_path,
        dataset="registrant_registry_delta",
        registry_id=registry_id,
        root=root,
        row_count=len(delta_rows),
        upstream=(registry_manifest["artifact_id"],),
    )
    worklist_manifest = _publish_parquet_manifest(
        path=worklist_path,
        dataset="metadata_augmentation_worklist",
        registry_id=registry_id,
        root=root,
        row_count=len(worklist_rows),
        upstream=(registry_manifest["artifact_id"],),
    )
    effective_csv = registry_root / "effective_cik_input.csv"
    csv_lines = ["cik,name"] + [
        f"{row['cik_padded']},{_csv_escape(row['canonical_name'])}"
        for row in registry_rows
    ]
    atomic_write_text(effective_csv, "\n".join(csv_lines) + "\n")
    effective_csv_manifest = {
        "manifest_kind": "effective_cik_input",
        "manifest_schema_version": REGISTRY_SCHEMA_VERSION,
        "registry_id": registry_id,
        "source_snapshot_id": source.manifest["snapshot_id"],
        "curated_input_path": str(curated_input_path),
        "curated_input_fingerprint": curated_report["fingerprint"],
        "artifact_path": effective_csv.relative_to(root).as_posix(),
        "artifact_sha256": file_sha256(effective_csv),
        "row_count": len(registry_rows),
        "columns": ["cik", "name"],
        "validation_status": "ok",
    }
    atomic_write_json(
        registry_root / "effective_cik_input.manifest.json",
        effective_csv_manifest,
        indent=None,
    )
    diff = {
        "registry_id": registry_id,
        "source_snapshot_id": source.manifest["snapshot_id"],
        "curated_input_fingerprint": curated_report["fingerprint"],
        "curated_count": len(curated_rows),
        "active_listing_row_count": len(listings),
        "active_unique_cik_count": len(active_by_cik),
        "overlap_count": len(set(curated_by_cik) & set(active_by_cik)),
        "active_only_cik_count": len(set(active_by_cik) - set(curated_by_cik)),
        "curated_only_cik_count": len(set(curated_by_cik) - set(active_by_cik)),
        "duplicate_listing_count": parse_report["duplicate_listing_count"],
        "malformed_row_count": parse_report["malformed_row_count"],
        "source_manifest_path": str(source_manifest_path),
        "listing_manifest_id": listing_manifest["artifact_id"],
        "registry_manifest_id": registry_manifest["artifact_id"],
        "delta_manifest_id": delta_manifest["artifact_id"],
        "worklist_manifest_id": worklist_manifest["artifact_id"],
        "effective_csv_manifest_path": str(
            registry_root / "effective_cik_input.manifest.json"
        ),
        "validation_status": "ok",
    }
    atomic_write_json(registry_root / "cik_diff.json", diff, indent=None)
    return {
        **diff,
        "registry_path": str(registry_path),
        "listing_path": str(listing_path),
        "new_ciks_path": str(delta_path),
        "worklist_path": str(worklist_path),
        "effective_csv_path": str(effective_csv),
    }


def _csv_escape(value: str) -> str:
    escaped = value.replace('"', '""')
    if any(character in escaped for character in (",", "\n", "\r", '"')):
        return f'"{escaped}"'
    return escaped


__all__ = ["compare_sources"]
