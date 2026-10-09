from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from edgar_sec.domain.filing_catalog.schemas import (
    TARGET_PLAN_SCHEMA_VERSION,
    TARGET_SCHEMA,
)
from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.pipelines.document_planning.discovery import read_published_plan
from edgar_sec.pipelines.document_planning.inventory_evidence import (
    CatalogAccessionScopeRow,
    InventoryEvidenceError,
    InventoryEvidenceRow,
)
from edgar_sec.pipelines.document_planning.paths import (
    resolve_catalog_paths,
    resolve_document_planning_paths,
)
from edgar_sec.pipelines.document_planning.planner import (
    DocumentPlanningError,
    create_document_plan,
)
from edgar_sec.pipelines.document_planning.schemas import TARGET_SCHEMA as PLAN_SCHEMA

_ACCESSION = "0000000001-24-000001"
_ARCHIVE_ACCESSION = "000000000124000001"


def _paths(tmp_path: Path):
    return resolve_document_planning_paths(tmp_path, tmp_path / "artifacts")


def _write_profile(paths, targets: list[dict[str, Any]]) -> None:
    paths.profiles_root.mkdir(parents=True, exist_ok=True)
    profile = {
        "profile_id": "test-profile",
        "schema_version": "1",
        "version": "1",
        "rules": [{"form_selector": "*", "targets": targets}],
    }
    (paths.profiles_root / "test-profile.json").write_text(
        json.dumps(profile), encoding="utf-8"
    )


def _catalog_row(**changes: Any) -> dict[str, Any]:
    row = {
        "occurrence_id": "occ-1",
        "document_locator_key": "locator-1",
        "source_cik": "0000000001",
        "accession": _ARCHIVE_ACCESSION,
        "form": "10-K",
        "filing_date": "2024-01-02",
        "report_date": None,
        "primary_document": "primary.htm",
        "document_path": "primary.htm",
        "archive_url": f"https://www.sec.gov/Archives/edgar/data/1/{_ARCHIVE_ACCESSION}/primary.htm",
        "document_path_source": "primary_document",
        "reported_size": 100,
        "is_xbrl": True,
        "is_inline_xbrl": False,
        "is_xbrl_numeric": True,
    }
    row.update(changes)
    return row


def _publish_catalog(paths, rows: list[dict[str, Any]] | None = None) -> None:
    selected = rows or [_catalog_row()]
    catalog_paths = resolve_catalog_paths(paths.artifacts_root)
    root = catalog_paths.plan_dir("catalog-plan")
    part = root / "targets" / "form=10-K" / "data.parquet"
    part.parent.mkdir(parents=True)
    table = pa.Table.from_pylist(selected, schema=TARGET_SCHEMA)
    pq.write_table(table, part, compression="zstd")
    manifest = {
        "plan_id": "catalog-plan",
        "plan_schema_version": TARGET_PLAN_SCHEMA_VERSION,
        "catalog_id": "catalog-snapshot",
        "scope": "deterministic",
        "plan_fingerprint": "catalog-fingerprint",
        "forms": [],
        "counts": {"10-K": len(selected)},
        "selected_rows": len(selected),
        "target_parts": [
            {
                "form": "10-K",
                "path": "targets/form=10-K/data.parquet",
                "row_count": len(selected),
                "byte_size": part.stat().st_size,
                "sha256": file_sha256(part),
            }
        ],
    }
    (root / "plan.json").write_text(json.dumps(manifest), encoding="utf-8")


def _target(role: str, target_type: str, *, optional: bool = False):
    return {"role": role, "type": target_type, "optional": optional}


def test_catalog_only_plan_is_pinned_sorted_and_identically_reused(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    _write_profile(paths, [_target("primary", "primary")])
    _publish_catalog(paths)

    first = create_document_plan("catalog-plan", "test-profile", paths=paths)
    second = create_document_plan("catalog-plan", "test-profile", paths=paths)
    validated = read_published_plan(first.plan_id, paths)
    target_path = validated.root / validated.manifest["parts"][0]["path"]
    target = pq.read_table(target_path, schema=PLAN_SCHEMA).to_pylist()[0]

    assert first.plan_id.startswith("dplan_")
    assert not first.reused
    assert second.reused
    assert first.manifest == second.manifest
    assert target["accession"] == _ACCESSION
    assert target["status"] == "matched"
    assert target["source_origin"] == "catalog_direct"
    assert target["availability_evidence"] == "catalog_metadata"
    assert target["target_url"].endswith("/primary.htm")
    assert target["inventory_entry_id"] is None
    assert first.manifest["inventory_snapshot_id"] is None
    assert first.manifest["inventory_snapshot_digest"] is None


def test_form_parts_have_deterministic_row_boundaries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _paths(tmp_path)
    _write_profile(paths, [_target("primary", "primary")])
    accessions = [f"00000000012400000{number}" for number in (1, 2, 3)]
    rows = [
        _catalog_row(
            occurrence_id=f"occ-{index}",
            accession=accession,
            document_locator_key=f"locator-{index}",
            archive_url=f"https://www.sec.gov/Archives/edgar/data/1/{accession}/primary.htm",
        )
        for index, accession in enumerate(accessions)
    ]
    _publish_catalog(paths, rows)
    monkeypatch.setattr("edgar_sec.pipelines.document_planning.planner._PART_ROWS", 2)
    monkeypatch.setattr("edgar_sec.pipelines.document_planning.discovery._PART_ROWS", 2)

    result = create_document_plan("catalog-plan", "test-profile", paths=paths)

    assert [part["rows"] for part in result.manifest["parts"]] == [2, 1]
    assert [part["path"].rsplit("/", 1)[-1] for part in result.manifest["parts"]] == [
        "part-00000.parquet",
        "part-00001.parquet",
    ]


class _Evidence:
    snapshot_id = "snapshot-1"
    snapshot_digest = "a" * 64

    def __init__(self, *, indexed: bool, mismatch: bool = False) -> None:
        self.indexed = indexed
        self.mismatch = mismatch

    def stream(self, accessions):
        for request in accessions:
            assert isinstance(request, CatalogAccessionScopeRow)
            if self.mismatch:
                raise InventoryEvidenceError("inventory facts disagree with catalog")
            if not self.indexed:
                yield InventoryEvidenceRow(
                    _ACCESSION,
                    request.form,
                    request.filing_date,
                    False,
                    None,
                    None,
                )
                continue
            accession_row = {
                "accession": _ACCESSION,
                "filing_cik": "0000000001",
                "form": "10-K",
                "filing_date": "2024-01-02",
                "bundle_url": f"https://www.sec.gov/Archives/edgar/data/1/{_ARCHIVE_ACCESSION}/{_ACCESSION}.txt",
            }
            entries = [
                {
                    "entry_id": "entry-primary",
                    "table_kind": "document_format",
                    "document_type": "10-K",
                    "sequence": 1,
                    "byte_size": 200,
                    "archive_url": f"https://www.sec.gov/Archives/edgar/data/1/{_ARCHIVE_ACCESSION}/primary.htm",
                },
                {
                    "entry_id": "entry-exhibit",
                    "table_kind": "document_format",
                    "document_type": "EX-21",
                    "sequence": 2,
                    "byte_size": 50,
                    "archive_url": None,
                    "href": None,
                },
                {
                    "entry_id": "entry-xbrl",
                    "table_kind": "data_file",
                    "document_type": "XML",
                    "description": "EXTRACTED XBRL INSTANCE DOCUMENT",
                    "sequence": 1,
                    "byte_size": 300,
                    "archive_url": f"https://www.sec.gov/Archives/edgar/data/1/{_ARCHIVE_ACCESSION}/Financial_Report.xlsx",
                },
            ]
            for entry in entries:
                yield InventoryEvidenceRow(
                    _ACCESSION,
                    request.form,
                    request.filing_date,
                    True,
                    accession_row,
                    entry,
                )


def test_inventory_plan_uses_pinned_index_and_distinguishes_package_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _paths(tmp_path)
    _write_profile(
        paths,
        [
            _target("primary", "primary"),
            _target("exhibit", "EX-21"),
            _target("data_file", "extracted_xbrl_instance"),
            _target("package", "xbrl_zip", optional=True),
        ],
    )
    _publish_catalog(paths)
    monkeypatch.setattr(
        "edgar_sec.pipelines.document_planning.planner._open_inventory",
        lambda _snapshot_id, _paths: _Evidence(indexed=True),
    )

    result = create_document_plan("catalog-plan", "test-profile", "snapshot-1", paths)
    plan = read_published_plan(result.plan_id, paths)
    rows = []
    for part in plan.manifest["parts"]:
        rows.extend(pq.read_table(plan.root / part["path"]).to_pylist())
    by_role = {row["target_role"]: row for row in rows}

    assert by_role["primary"]["source_origin"] == "inventory_index"
    assert by_role["primary"]["status"] == "matched"
    assert by_role["exhibit"]["retrieval_mode"] == "bundle_sequence"
    assert by_role["exhibit"]["sequence"] == 2
    assert by_role["data_file"]["status"] == "matched"
    assert by_role["package"]["status"] == "constructed_candidate"
    assert by_role["package"]["target_url"].endswith("-xbrl.zip")
    assert by_role["package"]["availability_evidence"] == "constructed"
    assert result.manifest["distinct_accession_coverage"]["inventory_indexed"] == 1


@pytest.mark.parametrize("mismatch", [False, True])
def test_unindexed_is_unresolved_and_catalog_mismatch_refuses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mismatch: bool,
) -> None:
    paths = _paths(tmp_path)
    _write_profile(paths, [_target("primary", "primary", optional=True)])
    _publish_catalog(paths)
    monkeypatch.setattr(
        "edgar_sec.pipelines.document_planning.planner._open_inventory",
        lambda _snapshot_id, _paths: _Evidence(indexed=False, mismatch=mismatch),
    )

    if mismatch:
        with pytest.raises(DocumentPlanningError, match="inventory facts disagree"):
            create_document_plan("catalog-plan", "test-profile", "snapshot-1", paths)
        return

    result = create_document_plan("catalog-plan", "test-profile", "snapshot-1", paths)
    plan = read_published_plan(result.plan_id, paths)
    target = pq.read_table(plan.root / plan.manifest["parts"][0]["path"]).to_pylist()[0]

    assert target["status"] == "unresolved"
    assert target["status_reason"] == "accession_not_indexed"
    assert target["source_origin"] == "inventory_index"
    assert target["availability_evidence"] == "none"
