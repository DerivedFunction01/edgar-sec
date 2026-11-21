"""Fixture paths and registry loading shared by tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

TESTS_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = TESTS_ROOT / "fixtures"
CATALOG_FIXTURES = FIXTURES / "catalog"

#: Canonical serialization of the retired standard_item_types.json, hashed
#: when the archive replaced it; the test and harness read it here (Step 4).
RETIRED_TABLE_SHA256 = (
    "1027f18d536540b1af00354a09c2f69c96eb5e53310da10ae93cb77a5634591b"
)
RETIRED_TABLE_SIZE = 18130


_CORPUS_DIRS = ("seed", "vintage", "sp100")


def corpus_dir(corpus: str) -> Path:
    """A cohort bundle corpus: package data beside the canonical registries."""
    from edgar_sec.engine.xbrl.discovery.cohort import DISCOVERY_DIR

    return DISCOVERY_DIR / corpus


def _resolve_fixture(name: str) -> Path:
    parts = name.split("/")
    if len(parts) >= 2 and parts[0] == "xbrl" and parts[1] in _CORPUS_DIRS:
        return corpus_dir(parts[1]).joinpath(*parts[2:])
    return FIXTURES / name


def load_fixture(name: str) -> Any:
    return json.loads(_resolve_fixture(name).read_text(encoding="utf-8"))


def fixture_path(name: str) -> Path:
    return _resolve_fixture(name)


def cohort_registry_path(name: str) -> Path:
    """Canonical cohort registries are package data, beside their loaders."""
    from edgar_sec.pipelines.xbrl_review.cohort import (
        PROBE_COHORT_FILE,
        canonical_probe_cohort_path,
    )

    if name == PROBE_COHORT_FILE:
        return canonical_probe_cohort_path()
    from edgar_sec.engine.xbrl.discovery.cohort import DISCOVERY_DIR

    return DISCOVERY_DIR / name


def load_cohort_registry(name: str) -> Any:
    return json.loads(cohort_registry_path(name).read_text(encoding="utf-8"))


def catalog_fixture_path(name: str) -> Path:
    return CATALOG_FIXTURES / name


def load_catalog_fixture(name: str) -> Any:
    return json.loads((CATALOG_FIXTURES / name).read_text(encoding="utf-8"))


__all__ = [
    "CATALOG_FIXTURES",
    "FIXTURES",
    "RETIRED_TABLE_SHA256",
    "RETIRED_TABLE_SIZE",
    "TESTS_ROOT",
    "catalog_fixture_path",
    "cohort_registry_path",
    "corpus_dir",
    "fixture_path",
    "load_catalog_fixture",
    "load_cohort_registry",
    "load_fixture",
]
