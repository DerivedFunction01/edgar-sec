"""Manifest-only discovery of classification product fixtures."""

from __future__ import annotations

from pathlib import Path

from edgar_sec.foundation.runtime.fixtures import fixtures_root

from ._db import fixture_paths, manifest_details, read_manifest
from .models import DATASET, FixtureStoreError, FixtureSummary


def discover_fixtures(artifacts_root: Path | str) -> tuple[FixtureSummary, ...]:
    """Summarize every readable fixture under the artifacts root."""
    root = fixtures_root(artifacts_root, DATASET)
    if not root.is_dir():
        return ()
    summaries: list[FixtureSummary] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        paths = fixture_paths(artifacts_root, child.name)
        try:
            envelope = read_manifest(paths)
            plan_pin, stamps = manifest_details(envelope)
        except FixtureStoreError:
            continue
        summaries.append(
            FixtureSummary(
                fixture_id=child.name,
                plan_pin=plan_pin,
                stamps=stamps,
                case_count=int(envelope.details.get("case_count", 0)),
            )
        )
    return tuple(summaries)
