"""Fixture paths and registry loading shared by tests."""

from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any

TESTS_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = TESTS_ROOT / "fixtures"
CATALOG_FIXTURES = FIXTURES / "catalog"
_TAXONOMY_FIXTURES = FIXTURES / "xbrl" / "taxonomy"

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


def _package_taxonomy_dir() -> Path:
    """The package taxonomy home: single source for mirrored fixture files."""
    from edgar_sec.foundation.runtime.paths import package_taxonomy_dir

    return package_taxonomy_dir()


def _review_sp100_cohort_path() -> Path:
    """The review-plane sp100 registry: home of the former taxonomy copy."""
    from edgar_sec.pipelines.xbrl_review.paths import default_sp100_cohort_path

    return default_sp100_cohort_path()


#: Package-home members of the benchmark taxonomy (Step 2 re-base: package
#: vocabulary is the standard; inflections — plurals are its generations only).
_PACKAGE_TAXONOMY_MEMBERS = (
    "atom_relations.json",
    "industries.json",
    "inflections.json",
    "prime_heads.json",
    "subatomic_modifiers.json",
    "token_lexicon.json",
)

#: Fixture-local benchmark members: geography (no package mirror) and the
#: authored empty sibling_groups stub.
_FIXTURE_TAXONOMY_MEMBERS = (
    "geography_dag.json",
    "sibling_groups.json",
)


def _derived_relation_types() -> bytes:
    """The benchmark relation_types reduction of the package home: entries
    minus PLACEMENT and DIALECT_OF, CONTRA_OF stripped of weight and formula.
    """
    entries = json.loads(
        (_package_taxonomy_dir() / "relation_types.json").read_text(encoding="utf-8")
    )
    kept = []
    for entry in entries:
        if entry["relation_type"] in ("PLACEMENT", "DIALECT_OF"):
            continue
        entry = dict(entry)
        if entry["relation_type"] == "CONTRA_OF":
            entry.pop("algebraic_weight", None)
            entry.pop("formula", None)
        kept.append(entry)
    return (json.dumps(kept, indent=2) + "\n").encode("utf-8")


def benchmark_taxonomy_dir() -> Path:
    """Materialize the benchmark taxonomy dir from its single homes: member
    lists plus derived relation_types, rebuilt when any source byte changes.
    """
    sources: dict[str, bytes] = {}
    for member in _PACKAGE_TAXONOMY_MEMBERS:
        sources[member] = (_package_taxonomy_dir() / member).read_bytes()
    for member in _FIXTURE_TAXONOMY_MEMBERS:
        sources[member] = (_TAXONOMY_FIXTURES / member).read_bytes()
    sources["relation_types.json"] = _derived_relation_types()
    digest = hashlib.sha256()
    for member in sorted(sources):
        digest.update(member.encode("utf-8"))
        digest.update(sources[member])
    root = (
        Path(tempfile.gettempdir())
        / "edgar-benchmark-taxonomy"
        / digest.hexdigest()[:16]
    )
    if not (root / "prime_heads.json").is_file():
        root.mkdir(parents=True, exist_ok=True)
        for member, payload in sources.items():
            (root / member).write_bytes(payload)
    return root


def _generated_catalog_path(name: str) -> Path | None:
    """The generated catalog fixtures, materialized from authored rows."""
    from tests.support.catalog_fixtures import (
        GENERATED_CATALOG_FIXTURES,
        catalog_fixture_dir,
    )

    if name in GENERATED_CATALOG_FIXTURES:
        return catalog_fixture_dir() / name
    return None


def _resolve_fixture(name: str) -> Path:
    parts = name.split("/")
    if len(parts) == 2 and parts[0] == "catalog":
        generated = _generated_catalog_path(parts[1])
        if generated is not None:
            return generated
    if len(parts) >= 2 and parts[0] == "xbrl" and parts[1] in _CORPUS_DIRS:
        return corpus_dir(parts[1]).joinpath(*parts[2:])
    if name == "xbrl/taxonomy":
        return benchmark_taxonomy_dir()
    if name == "xbrl/taxonomy/sp100_cohort.json":
        return _review_sp100_cohort_path()
    if name in (
        "xbrl/taxonomy/industries.json",
        "xbrl/taxonomy/prime_heads.json",
    ):
        return _package_taxonomy_dir() / Path(name).name
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
    generated = _generated_catalog_path(name)
    if generated is not None:
        return generated
    return CATALOG_FIXTURES / name


def load_catalog_fixture(name: str) -> Any:
    return json.loads((CATALOG_FIXTURES / name).read_text(encoding="utf-8"))


__all__ = [
    "CATALOG_FIXTURES",
    "FIXTURES",
    "RETIRED_TABLE_SHA256",
    "RETIRED_TABLE_SIZE",
    "TESTS_ROOT",
    "benchmark_taxonomy_dir",
    "catalog_fixture_path",
    "cohort_registry_path",
    "corpus_dir",
    "fixture_path",
    "load_catalog_fixture",
    "load_cohort_registry",
    "load_fixture",
]
