"""Automated gate collision auditing, sole-match evaluation, family relations, and empirical geometry."""

from __future__ import annotations

import collections
import statistics
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Sequence


def compute_geometry_stats(records: Sequence[dict[str, Any]]) -> dict[str, object]:
    """Compute empirical post-healing 2D geometry distributions."""
    if not records:
        return {}

    healed_cols = [int(r["healed_cols"]) for r in records]
    healed_rows = [int(r["healed_rows"]) for r in records]
    densities = [float(r["numeric_density"]) for r in records]
    hdr_counts = [int(r.get("header_count", 1)) for r in records]
    jitter_flags = [bool(r.get("has_column_jitter", False)) for r in records]
    split_flags = [bool(r.get("has_split_affixes", False)) for r in records]

    col_freq = collections.Counter(healed_cols)
    hdr_freq = collections.Counter(hdr_counts)

    return {
        "count": len(records),
        "healed_cols": {
            "avg": round(statistics.mean(healed_cols), 2),
            "min": min(healed_cols),
            "max": max(healed_cols),
            "distribution": dict(sorted(col_freq.items())),
        },
        "healed_rows": {
            "avg": round(statistics.mean(healed_rows), 2),
            "min": min(healed_rows),
            "max": max(healed_rows),
        },
        "numeric_density": {
            "mean": round(statistics.mean(densities), 4),
            "min": round(min(densities), 4),
            "max": round(max(densities), 4),
        },
        "header_depth": dict(sorted(hdr_freq.items())),
        "jitter_pct": round(sum(jitter_flags) / len(records) * 100, 2),
        "split_affixes_pct": round(sum(split_flags) / len(records) * 100, 2),
    }


def compute_collision_matrix(
    family_matches: dict[str, set[int]],
) -> dict[str, dict[str, int]]:
    """Compute cross-family collision / co-occurrence matrix."""
    matrix: dict[str, dict[str, int]] = {
        name: collections.defaultdict(int) for name in family_matches
    }

    for name_a, slots_a in family_matches.items():
        for name_b, slots_b in family_matches.items():
            if name_a == name_b:
                matrix[name_a][name_b] = len(slots_a)
            else:
                matrix[name_a][name_b] = len(slots_a.intersection(slots_b))

    return {k: dict(v) for k, v in matrix.items()}


def compute_family_relations(
    family_matches: dict[str, set[int]],
) -> list[dict[str, object]]:
    """Compute cross-family relations, subsumptions, and directional overlaps."""
    relations: list[dict[str, object]] = []

    for name_a, slots_a in family_matches.items():
        if not slots_a:
            continue
        for name_b, slots_b in family_matches.items():
            if name_a == name_b or not slots_b:
                continue

            intersection = slots_a.intersection(slots_b)
            if not intersection:
                continue

            overlap_count = len(intersection)
            overlap_rate_a = overlap_count / len(slots_a)
            overlap_rate_b = overlap_count / len(slots_b)

            rel_type = "overlap"
            if overlap_count == len(slots_a) and overlap_count < len(slots_b):
                rel_type = f"{name_a} is strict subset of {name_b}"
            elif overlap_count == len(slots_b) and overlap_count < len(slots_a):
                rel_type = f"{name_b} is strict subset of {name_a}"
            elif overlap_count == len(slots_a) and overlap_count == len(slots_b):
                rel_type = "identical match set"

            relations.append(
                {
                    "family_a": name_a,
                    "family_b": name_b,
                    "overlap_count": overlap_count,
                    "rate_in_a": round(overlap_rate_a, 3),
                    "rate_in_b": round(overlap_rate_b, 3),
                    "relation_type": rel_type,
                }
            )

    relations.sort(key=lambda x: int(x["overlap_count"]), reverse=True)
    return relations


import concurrent.futures
import json

from tqdm import tqdm

from defs.taxonomy.tables.classifier import classify_table


def eval_record_batch(
    batch: list[tuple[int, str | None]],
) -> list[tuple[int, str | None]]:
    """Process a chunk of table records in a worker process."""
    results: list[tuple[int, str | None]] = []
    for slot, grid_raw in batch:
        if grid_raw:
            try:
                grid = json.loads(grid_raw)
            except (json.JSONDecodeError, TypeError, ValueError):
                grid = []
        else:
            grid = []
        res = classify_table(grid)
        results.append((slot, res.family))
    return results


def run_benchmark_classifier(
    bench_records: Sequence[dict[str, Any]],
    active_family_names: Sequence[str],
    workers: int = 4,
) -> tuple[dict[str, set[int]], set[int]]:
    """Run parallel multi-zone BoW classifier benchmark over table records."""
    matches_per_family: dict[str, set[int]] = {
        name: set() for name in active_family_names
    }
    classified_slots: set[int] = set()

    chunk_size = max(500, len(bench_records) // (max(1, workers) * 8))
    batches: list[list[tuple[int, str | None]]] = []
    for i in range(0, len(bench_records), chunk_size):
        chunk = [
            (i + j, r.get("healed_grid_json"))
            for j, r in enumerate(bench_records[i : i + chunk_size])
        ]
        batches.append(chunk)

    with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(eval_record_batch, b) for b in batches]
        for f in tqdm(
            concurrent.futures.as_completed(futures),
            total=len(futures),
            desc="Benchmarking classifier",
            unit="chunk",
        ):
            for slot, family in f.result():
                if family and family in matches_per_family:
                    matches_per_family[family].add(slot)
                    classified_slots.add(slot)

    return matches_per_family, classified_slots


__all__ = [
    "compute_collision_matrix",
    "compute_family_relations",
    "compute_geometry_stats",
    "eval_record_batch",
    "run_benchmark_classifier",
]
