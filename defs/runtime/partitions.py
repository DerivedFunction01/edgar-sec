"""Shared partition selection and work distribution helpers."""

from __future__ import annotations


def parse_id_selection(spec: str, known_ids: list[int], label: str = "id") -> list[int]:
    known = set(known_ids)
    selected: list[int] = []
    for part in spec.replace(" ", "").split(","):
        if not part:
            continue
        try:
            if "-" in part:
                start, end = (int(value) for value in part.split("-", 1))
                selected.extend(range(min(start, end), max(start, end) + 1))
            else:
                selected.append(int(part))
        except ValueError as exc:
            raise ValueError(f"invalid {label} selection: {part!r}") from exc
    unknown = sorted(set(selected) - known)
    if unknown:
        raise ValueError(f"unknown {label}s: {unknown}")
    return sorted(dict.fromkeys(selected))


def divide_ids_among_workers(ids: list[int], workers: int) -> list[list[int]]:
    if workers < 1:
        raise ValueError("workers must be >= 1")
    groups = [[] for _ in range(workers)]
    base, remainder = divmod(len(ids), workers)
    offset = 0
    for index in range(workers):
        count = base + (index < remainder)
        groups[index] = ids[offset : offset + count]
        offset += count
    return groups


__all__ = ["divide_ids_among_workers", "parse_id_selection"]
