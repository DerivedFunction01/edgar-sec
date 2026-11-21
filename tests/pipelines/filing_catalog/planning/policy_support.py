"""Shared policy builders for the filing-catalog planning policy suites."""

from __future__ import annotations

from pathlib import Path

from edgar_sec.engine.selection.policy import EraBand, SelectionPolicy


def _policy(**overrides: object) -> SelectionPolicy:
    base: dict[str, object] = {
        "corpus_id": "policy_corpus",
        "forms": ["10-K", "8-K"],
        "era_bands": [EraBand(name="modern", start_year=2010)],
        "base_content_units": 3,
        "reserve_size": 1,
    }
    base.update(overrides)
    return SelectionPolicy(**base)  # type: ignore[arg-type]


def _artifacts_root(catalog_artifacts_root: Path) -> Path:
    """The shared fixture, not ``parents[N]``, which would pin the published depth."""
    return catalog_artifacts_root
