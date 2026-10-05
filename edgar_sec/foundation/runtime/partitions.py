"""Partition range parsing and worker workload distribution."""

from __future__ import annotations


def parse_id_selection(spec: str) -> tuple[int, ...]:
    """Parse comma-separated partition integers and ranges (e.g. '1-3,5' -> (1, 2, 3, 5))."""
    cleaned = spec.strip()
    if not cleaned:
        return ()

    results: set[int] = set()
    for token in cleaned.split(","):
        part = token.strip()
        if not part:
            continue
        if "-" in part:
            start_str, _, end_str = part.partition("-")
            start = int(start_str.strip())
            end = int(end_str.strip())
            if start > end:
                raise ValueError(
                    f"invalid range '{part}': start ({start}) > end ({end})"
                )
            results.update(range(start, end + 1))
        else:
            results.add(int(part))

    return tuple(sorted(results))


def divide_ids_among_workers(
    ids: tuple[int, ...] | list[int],
    worker_count: int,
) -> list[tuple[int, ...]]:
    """Divide a sequence of IDs into balanced buckets for concurrent worker execution."""
    if worker_count <= 0:
        raise ValueError(f"worker_count must be positive, got {worker_count}")
    if not ids:
        return []

    buckets: list[list[int]] = [[] for _ in range(min(worker_count, len(ids)))]
    for idx, item in enumerate(ids):
        buckets[idx % len(buckets)].append(item)

    return [tuple(b) for b in buckets if b]


__all__ = ["divide_ids_among_workers", "parse_id_selection"]
