"""Batch-streamed cohort scans with runtime-derived batch sizing.

Batch cardinality is the runtime memory budget divided by a measured
per-bundle resident footprint; no batch size or worker count is a
constant anywhere in this module.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass

import pyarrow.parquet as pq

from edgar_sec.engine.xbrl.solve.concept_table import CohortEntry
from edgar_sec.foundation.runtime.memory import reclaim
from edgar_sec.foundation.runtime.resources import (
    DEFAULT_WORKER_MEMORY_SAFETY,
    RuntimeResourceProfile,
    auto_worker_count,
    derive_resources,
    usable_memory_bytes,
)

_MEBIBYTE = 1024 * 1024


@dataclass(frozen=True, slots=True)
class CohortScanPlan:
    """Derived scan sizing: batch cardinality and the parallel worker budget."""

    batch_cardinality: int
    worker_budget: int
    footprint_bytes: int
    available_bytes: int


def measure_bundle_footprint(facts_path: object) -> int:
    """Resident bytes of one bundle's facts in Arrow representation."""
    table = pq.read_table(str(facts_path))
    return max(1, int(table.nbytes))


def derive_batch_cardinality(
    available_bytes: int,
    footprint_bytes: int,
    *,
    safety_fraction: float = DEFAULT_WORKER_MEMORY_SAFETY,
) -> int:
    """Bundles resident at once: the usable budget over the footprint."""
    if footprint_bytes < 1:
        raise ValueError("footprint_bytes must be >= 1")
    usable = usable_memory_bytes(available_bytes, safety_fraction=safety_fraction)
    return max(1, usable // footprint_bytes)


def plan_cohort_scan(
    entries: Sequence[CohortEntry],
    *,
    profile: RuntimeResourceProfile | None = None,
    available_bytes: int | None = None,
    footprint_bytes: int | None = None,
) -> CohortScanPlan:
    """Derive the scan plan for a cohort from the runtime resource budget."""
    if not entries:
        raise ValueError("a cohort scan needs at least one entry")
    if profile is None:
        profile = derive_resources()
    available = (
        available_bytes
        if available_bytes is not None
        else profile.available_memory_bytes
    )
    footprint = (
        footprint_bytes
        if footprint_bytes is not None
        else measure_bundle_footprint(entries[0].facts_path)
    )
    cardinality = min(len(entries), derive_batch_cardinality(available, footprint))
    workers = auto_worker_count(
        available,
        worker_memory_mib=max(1, footprint // _MEBIBYTE),
        safety_fraction=profile.worker_memory_safety,
        cpu_cores=profile.cpu_cores,
    )
    return CohortScanPlan(
        batch_cardinality=cardinality,
        worker_budget=workers,
        footprint_bytes=footprint,
        available_bytes=available,
    )


def iter_cohort_batches(
    entries: Sequence[CohortEntry],
    *,
    profile: RuntimeResourceProfile | None = None,
    available_bytes: int | None = None,
    footprint_bytes: int | None = None,
) -> Iterator[tuple[tuple[CohortEntry, ...], tuple[object, ...]]]:
    """Yield (entries, Arrow fact tables) per batch, reclaiming between batches.

    Batches may be processed in parallel up to the plan's worker budget;
    residency stays bounded by the batch cardinality either way.
    """
    if not entries:
        return
    plan = plan_cohort_scan(
        entries,
        profile=profile,
        available_bytes=available_bytes,
        footprint_bytes=footprint_bytes,
    )
    step = plan.batch_cardinality
    for start in range(0, len(entries), step):
        batch = tuple(entries[start : start + step])
        tables = tuple(pq.read_table(str(entry.facts_path)) for entry in batch)
        yield batch, tables
        reclaim()


__all__ = [
    "CohortScanPlan",
    "derive_batch_cardinality",
    "iter_cohort_batches",
    "measure_bundle_footprint",
    "plan_cohort_scan",
]
