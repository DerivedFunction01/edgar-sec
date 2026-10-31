from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from edgar_sec.infra.storage.duckdb import connect
from edgar_sec.pipelines.document_inventory.paths import (
    PLAN_TARGETS_DIR,
    InventoryPaths,
    resolve_filing_catalog_paths,
)


def form_lookup_for_review_records(
    records: list[dict], artifacts_root: Path | None
) -> dict[str, set[str]]:
    if artifacts_root is None:
        return {}
    accessions = {
        record["accession"].replace("-", "")
        for record in records
        if isinstance(record.get("accession"), str)
    }
    if not accessions:
        return {}

    inventory_paths = InventoryPaths(artifacts_root)
    catalog_paths = resolve_filing_catalog_paths(artifacts_root)
    fixture_ids = {
        record["fixture_id"]
        for record in records
        if isinstance(record.get("fixture_id"), str) and record["fixture_id"]
    }
    plan_ids = set()
    for fixture_id in fixture_ids:
        manifest_path = inventory_paths.fixture_manifest_path(fixture_id)
        if not manifest_path.is_file():
            continue
        fixture_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        contributions = fixture_manifest.get("details", {}).get("contributions", [])
        plan_ids.update(
            contribution.get("plan_id")
            for contribution in contributions
            if isinstance(contribution.get("plan_id"), str)
        )

    target_files = []
    for plan_id in sorted(plan_ids):
        plan_targets = catalog_paths.plan_dir(plan_id) / PLAN_TARGETS_DIR
        target_files.extend(sorted(plan_targets.glob("form=*/**/*.parquet")))
    if not target_files:
        return {}

    query = (
        "SELECT accession, form FROM read_parquet(?) "
        "WHERE replace(CAST(accession AS VARCHAR), '-', '') "
        "IN (SELECT UNNEST(?))"
    )
    forms = defaultdict(set)
    with connect() as connection:
        for target_file in target_files:
            rows = connection.execute(
                query, [str(target_file), sorted(accessions)]
            ).fetchall()
            for accession, form in rows:
                forms[str(accession).replace("-", "")].add(str(form))
    return forms
