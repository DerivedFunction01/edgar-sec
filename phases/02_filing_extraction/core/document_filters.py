"""Shared document-path filters for Phase 02 planning."""

from __future__ import annotations


def normalize_suffixes(values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            suffix.strip().lower().lstrip(".")
            for suffix in values
            if str(suffix).strip().lstrip(".")
        )
    )


def suffix_sql(column: str, suffixes: tuple[str, ...]) -> str:
    if not suffixes:
        return "TRUE"
    return " OR ".join(f"lower({column}) LIKE '%.{suffix}'" for suffix in suffixes)
