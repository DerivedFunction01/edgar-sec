from __future__ import annotations

import json
from pathlib import Path

import pyarrow as pa

from edgar_sec.pipelines.document_planning.comparison import (
    _target_differences,
    compare_profiles,
)
from edgar_sec.pipelines.document_planning.discovery import PublishedDocumentPlan
from edgar_sec.pipelines.document_planning.paths import resolve_document_planning_paths
from edgar_sec.pipelines.document_planning.schemas import TARGET_SCHEMA


def _target(
    status: str, reason: str | None, *, accession: str = "0000320193-24-000001"
) -> dict:
    return {
        "target_id": f"target-{accession}-{status}",
        "accession": accession,
        "form": "10-K",
        "filing_date": "2024-01-15",
        "request_id": "primary:primary",
        "target_role": "primary",
        "target_type": "primary",
        "optional": False,
        "inventory_entry_id": "entry-1",
        "status": status,
        "status_reason": reason,
        "source_origin": "inventory_index",
        "retrieval_mode": "direct_url",
        "target_url": "https://example.test/document.htm",
        "sequence": 1,
        "byte_size": 10,
        "availability_evidence": "fixture",
        "catalog_direct_selection": None,
    }


def _plan(plan_id: str) -> PublishedDocumentPlan:
    return PublishedDocumentPlan(
        plan_id,
        Path("."),
        {
            "parts": [],
            "catalog_plan_id": "catalog-1",
            "catalog_plan_digest": "a" * 64,
            "inventory_snapshot_id": "snapshot-1",
            "inventory_snapshot_digest": "b" * 64,
        },
    )


def test_target_comparison_reports_keyed_changes_and_status_reason_diffs(
    monkeypatch,
) -> None:
    rows = {
        "base_targets": [
            _target("unresolved", "missing"),
            _target("matched", "old", accession="0000320193-24-000002"),
            _target("unresolved", "removed", accession="0000320193-24-000003"),
        ],
        "new_targets": [
            _target("matched", None),
            _target("matched", "new", accession="0000320193-24-000002"),
            _target("matched", None, accession="0000320193-24-000004"),
        ],
    }

    def register(con, name, _parts):
        con.register(
            f"{name}_data", pa.Table.from_pylist(rows[name], schema=TARGET_SCHEMA)
        )
        con.execute(f"CREATE TEMP VIEW {name} AS SELECT * FROM {name}_data")

    monkeypatch.setattr(
        "edgar_sec.pipelines.document_planning.comparison._register_targets", register
    )

    counts, changes = _target_differences(_plan("base"), _plan("new"))

    assert counts == {
        "added": 1,
        "removed": 1,
        "status_transition": 1,
        "status_reason_change": 1,
    }
    assert [change["kind"] for change in changes] == [
        "status_transition",
        "status_reason_change",
        "removed",
        "added",
    ]


def test_status_transitions_are_suppressed_when_source_pins_change(monkeypatch) -> None:
    rows = {
        "base_targets": [_target("unresolved", "old")],
        "new_targets": [_target("matched", "old")],
    }

    def register(con, name, _parts):
        con.register(
            f"{name}_data", pa.Table.from_pylist(rows[name], schema=TARGET_SCHEMA)
        )
        con.execute(f"CREATE TEMP VIEW {name} AS SELECT * FROM {name}_data")

    monkeypatch.setattr(
        "edgar_sec.pipelines.document_planning.comparison._register_targets", register
    )
    new = _plan("new")
    new.manifest["inventory_snapshot_digest"] = "c" * 64

    counts, changes = _target_differences(_plan("base"), new)

    assert counts["status_transition"] == 0
    assert changes == []


def test_profile_diff_uses_normalized_selector_and_target_identity(
    tmp_path: Path,
) -> None:
    paths = resolve_document_planning_paths(tmp_path, tmp_path / "artifacts")
    paths.profiles_root.mkdir(parents=True)
    for profile_id, optional in (("before", False), ("after", True)):
        (paths.profiles_root / f"{profile_id}.json").write_text(
            json.dumps(
                {
                    "profile_id": profile_id,
                    "schema_version": "1",
                    "version": "1.0.0",
                    "rules": [
                        {
                            "form_selector": "10-K/A",
                            "targets": [
                                {
                                    "role": "primary",
                                    "type": "primary",
                                    "optional": optional,
                                }
                            ],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

    diff = compare_profiles("before", "after", paths)

    assert diff["status"] == "compared"
    assert diff["removed"][0]["form_selector"] == "10-K"
    assert diff["added"][0]["optional"] is True
