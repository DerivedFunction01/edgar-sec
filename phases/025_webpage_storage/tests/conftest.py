"""Pytest setup and offline fixture bundle builders for Phase 2.5 tests."""

from __future__ import annotations

import importlib
import json
import sys
from contextlib import suppress
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

from defs.runtime.paths import resolve_paths
from defs.sql import DoNothing, insert_values, make_sql_executor
from defs.storage import pa, write_table_atomic

phases_025 = importlib.import_module("phases.025_webpage_storage.core.schemas")


def _write_parquet(path: Path, rows: list[dict]) -> None:
    table = pa.Table.from_pylist(rows if rows else [{"placeholder": 1}])
    path.parent.mkdir(parents=True, exist_ok=True)
    write_table_atomic(table, path)


def build_phase02_bundle(
    root: Path,
    *,
    documents: dict[str, bytes] | None = None,
    occurrences: list[dict] | None = None,
):
    """Create a minimal Phase 02 plan bundle for offline tests."""
    if documents is None:
        documents = {
            "000000000100000001/10k.htm": b"<html>alpha</html>",
            "000000000100000001/10k2.htm": b"<html>beta</html>",
        }
    if occurrences is None:
        occurrences = [
            {
                "occurrence_id": "occ-1",
                "document_locator_key": "loc-1",
                "source_cik": "0000000001",
                "accession": "000000000100000001",
                "form": "10-K",
                "filing_date": "2024-01-02",
                "report_date": "2023-12-31",
                "document_path": "10k.htm",
            },
            {
                "occurrence_id": "occ-2",
                "document_locator_key": "loc-2",
                "source_cik": "0000000001",
                "accession": "000000000100000001",
                "form": "10-K",
                "filing_date": "2024-01-02",
                "report_date": "2023-12-31",
                "document_path": "10k2.htm",
            },
        ]
    locator_rows = [
        {
            "document_locator_key": occ["document_locator_key"],
            "form": occ["form"],
            "representative_cik": occ["source_cik"],
            "representative_accession": occ["accession"],
            "primary_document": occ["document_path"],
            "document_path": occ["document_path"],
            "archive_url": f"https://www.sec.gov/Archives/{occ['accession']}/{occ['document_path']}",
        }
        for occ in occurrences
    ]
    (root / "targets" / "form=10-K").mkdir(parents=True, exist_ok=True)
    _write_parquet(root / "locator_groups.parquet", locator_rows)
    _write_parquet(root / "targets" / "form=10-K" / "data.parquet", occurrences)
    (root / "plan.json").write_text(
        json.dumps(
            {
                "scope": "full",
                "plan_schema_version": 1,
                "unique_locators_count": len(locator_rows),
            }
        ),
        encoding="utf-8",
    )
    (root / "selection_report.json").write_text(
        json.dumps({"active_targets_count": len(occurrences)}), encoding="utf-8"
    )
    return root


def build_fixture_sqlite(fixture_id: str, documents: dict[str, bytes]) -> Path:
    fixture_paths = resolve_paths().fixture(fixture_id, dialect="sqlite")
    fixture_paths.ensure_layout()
    database = fixture_paths.db_path
    database.touch()
    executor = make_sql_executor(database, dialect="sqlite")
    try:
        phases_025.create_schema(executor, phases_025.chunk_ddl())
        for key, raw in documents.items():
            accession, document_path = key.split("/", 1)
            blob = phases_025.build_blob(accession, document_path, raw)
            executor.transaction(
                (
                    executor.compiler.compile(
                        insert_values(
                            phases_025.DOCUMENT_BLOBS_TABLE,
                            blob.to_row(),
                            on_conflict=DoNothing(),
                        )
                    ),
                )
            )
    finally:
        executor.close()
    return database


@pytest.fixture
def phase02_bundle(tmp_path):
    return build_phase02_bundle(tmp_path / "plan")


@pytest.fixture
def fixture_database():
    import shutil
    import uuid

    fixture_id = f"test-fixture-{uuid.uuid4().hex[:8]}"
    fixture_paths = resolve_paths().fixture(fixture_id, dialect="sqlite")
    database = build_fixture_sqlite(
        fixture_id,
        {
            "000000000100000001/10k.htm": b"<html>alpha</html>",
            "000000000100000001/10k2.htm": b"<html>beta</html>",
        },
    )
    yield database
    with suppress(Exception):
        if fixture_paths.root.is_dir():
            shutil.rmtree(fixture_paths.root)
