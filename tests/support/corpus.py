"""Corpus bundle access: bundle folders, texts, and registry rows."""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any

from tests.support.fixtures import corpus_dir, load_cohort_registry

_CORPUS_NAMES = ("seed", "vintage", "sp100")


def bundle_dir(folder: str) -> Path:
    """A corpus bundle folder; it must exist in exactly one corpus root."""
    hits = [
        corpus_dir(corpus) / folder
        for corpus in _CORPUS_NAMES
        if (corpus_dir(corpus) / folder).is_dir()
    ]
    if len(hits) != 1:
        raise ValueError(f"bundle folder {folder} in {len(hits)} corpus roots")
    return hits[0]


def bundle_text(folder: str) -> str:
    """A corpus bundle's normalized filing text (stored gzipped)."""
    path = bundle_dir(folder) / "normalized_text.txt.gz"
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return handle.read()


def corpus_cohort_rows() -> list[dict[str, Any]]:
    """All canonical cohort registry rows: seed, vintage, then SP100."""
    rows: list[dict[str, Any]] = []
    for name in ("seed_cohort.json", "vintage_cohort.json", "sp100_cohort.json"):
        rows.extend(load_cohort_registry(name))
    return rows


def corpus_source_bundles() -> list[dict[str, Any]]:
    """All fixture source registry rows: seed, vintage, then SP100."""
    bundles: list[dict[str, Any]] = []
    for corpus in _CORPUS_NAMES:
        payload = json.loads(
            (corpus_dir(corpus) / "fixture_source_registry.json").read_text(
                encoding="utf-8"
            )
        )
        bundles.extend(payload["bundles"])
    return bundles


__all__ = [
    "bundle_dir",
    "bundle_text",
    "corpus_cohort_rows",
    "corpus_source_bundles",
]
