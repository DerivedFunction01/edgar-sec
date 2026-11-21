"""Reader: provenance-carrying reads and honest absence."""

from __future__ import annotations

import json
from pathlib import Path

from edgar_sec.pipelines.table_classification.paths import ClassificationPaths
from edgar_sec.pipelines.table_classification.reader import (
    ClassificationStoreReader,
)
from edgar_sec.pipelines.table_classification.store import publish_merged_run

from .test_store import ACCESSION, PLAN_ID, PUBLISHED_AT, write_run


def _reader(tmp_path: Path) -> ClassificationStoreReader:
    return ClassificationStoreReader(ClassificationPaths(artifacts_root=tmp_path))


def test_absent_store_reads_as_absence(tmp_path: Path) -> None:
    reader = _reader(tmp_path)
    assert reader.tip_snapshot_id() is None
    assert reader.provenance() is None
    assert reader.classified_tables(ACCESSION) is None
    assert reader.filing_accessions() == ()


def test_reads_carry_provenance_and_join_inventory(tmp_path: Path) -> None:
    paths = ClassificationPaths(artifacts_root=tmp_path)
    write_run(paths)
    result = publish_merged_run(paths, PLAN_ID, published_at=PUBLISHED_AT)
    reader = _reader(tmp_path)

    assert reader.tip_snapshot_id() == result.snapshot_id
    provenance = reader.provenance()
    assert provenance is not None
    assert provenance.store_snapshot_id == result.snapshot_id
    assert provenance.source_snapshot_id == "acq-snapshot-1"
    assert provenance.plan_id == PLAN_ID
    assert provenance.plan_format_version == "1.0.0"
    assert provenance.run_output_version == "1.0.0"
    assert (
        provenance.registry_state
        == "sha256:0264d35b20eb338684cd4b50143f946442a333377bbff01a96e1da58952697ec"
    )
    assert provenance.normalize_version == "norm-1"
    assert provenance.renderer_version == "rend-1"

    read = reader.classified_tables(ACCESSION)
    assert read is not None
    assert read.provenance.store_snapshot_id == result.snapshot_id
    assert len(read.tables) == 1
    row = read.tables[0]
    assert row.family == "balance_sheet"
    assert row.kind == "statement"
    assert row.tier == "confident"
    assert row.score == 12.5
    assert row.source_document == "primary"
    assert row.table_index == 0
    assert row.provenance_route == "render_to_txt"
    assert row.assembled_family == "balance_sheet"
    assert row.mechanism == "assembly"
    assert json.loads(row.evidence)[0]["group"] == "caption"

    assert reader.filing_accessions() == (ACCESSION,)


def test_missing_filing_reads_as_absence(tmp_path: Path) -> None:
    paths = ClassificationPaths(artifacts_root=tmp_path)
    write_run(paths)
    publish_merged_run(paths, PLAN_ID, published_at=PUBLISHED_AT)
    reader = _reader(tmp_path)
    assert reader.classified_tables("0009999999-26-000009") is None
