"""Tests for batch-streamed cohort scans with runtime-derived sizing."""

from __future__ import annotations

from pathlib import Path

import pyarrow.parquet as pq
import pytest

from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.engine.xbrl.schema.models import XbrlFact
from edgar_sec.engine.xbrl.solve.cohort_scan import (
    derive_batch_cardinality,
    iter_cohort_batches,
    measure_bundle_footprint,
    plan_cohort_scan,
)
from edgar_sec.engine.xbrl.solve.concept_table import CohortEntry
from edgar_sec.engine.xbrl.storage.storage import write_facts_parquet
from tests.engine.xbrl.solve.conftest import load_seed_cohort


def test_cardinality_is_budget_over_footprint() -> None:
    """Smaller budgets yield smaller batches; the floor is one bundle."""
    assert derive_batch_cardinality(10_000, 1_000) == 9
    assert derive_batch_cardinality(2_000, 1_000) == 1
    assert derive_batch_cardinality(500, 1_000) == 1
    assert derive_batch_cardinality(10_000, 1_000) > derive_batch_cardinality(
        5_000, 1_000
    )


def test_cardinality_rejects_empty_footprint() -> None:
    """A footprint must be a positive measured size."""
    with pytest.raises(ValueError, match="footprint"):
        derive_batch_cardinality(10_000, 0)


def _entries(tmp_path: Path, count: int) -> tuple[CohortEntry, ...]:
    entries = []
    for index in range(count):
        path = tmp_path / f"firm{index}" / "facts.parquet"
        write_facts_parquet(
            [
                XbrlFact(
                    accession=AccessionNumber.from_any(f"000000000{index}-24-000001"),
                    concept_qname="us-gaap:Revenues",
                    value=float(index),
                    unit="USD",
                    period_type="duration",
                    start_date="2024-01-01",
                    end_date="2024-12-31",
                )
            ],
            path,
        )
        entries.append(
            CohortEntry(
                accession=f"000000000{index}-24-000001",
                facts_path=path,
                firm=f"F{index}",
            )
        )
    return tuple(entries)


def test_scan_batches_bound_by_stubbed_budget(tmp_path: Path) -> None:
    """A one-bundle budget streams one bundle per batch, each exactly once."""
    entries = _entries(tmp_path, 3)
    footprint = measure_bundle_footprint(entries[0].facts_path)
    batches = list(
        iter_cohort_batches(
            entries, available_bytes=footprint, footprint_bytes=footprint
        )
    )
    assert [len(batch) for batch, _ in batches] == [1, 1, 1]
    seen = [entry for batch, _ in batches for entry in batch]
    assert seen == list(entries)
    assert all(table.num_rows == 1 for _, tables in batches for table in tables)


def test_scan_plan_derives_from_budget(tmp_path: Path) -> None:
    """The plan's cardinality and worker budget follow the stubbed budget."""
    entries = _entries(tmp_path, 3)
    footprint = measure_bundle_footprint(entries[0].facts_path)
    plan = plan_cohort_scan(
        entries, available_bytes=footprint * 2, footprint_bytes=footprint
    )
    assert plan.footprint_bytes == footprint
    assert plan.batch_cardinality == 1
    assert plan.worker_budget >= 1


def test_full_cohort_scan_covers_every_row() -> None:
    """A cohort pass yields each bundle's facts exactly once, batched."""
    entries = load_seed_cohort()
    expected_rows = sum(
        pq.ParquetFile(entry.facts_path).metadata.num_rows for entry in entries
    )
    plan = plan_cohort_scan(entries, available_bytes=64 * 1024 * 1024)
    total = 0
    seen = 0
    for batch, tables in iter_cohort_batches(entries, available_bytes=64 * 1024 * 1024):
        assert len(batch) <= plan.batch_cardinality
        assert len(batch) == len(tables)
        seen += len(batch)
        total += sum(table.num_rows for table in tables)
    assert seen == len(entries)
    assert total == expected_rows
