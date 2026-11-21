"""Tests for XBRL artifact paths resolution."""

from pathlib import Path

import pytest

from edgar_sec.engine.xbrl.paths import default_taxonomy_dir, resolve_xbrl_paths
from edgar_sec.foundation.runtime.paths import (
    ENGINE_DIR,
    PACKAGE_ROOT,
    TAXONOMY_DIR,
    XBRL_DIR,
)


def test_resolve_xbrl_paths(tmp_path: Path) -> None:
    """Verify artifact directory and taxonomy path generation."""
    paths = resolve_xbrl_paths(artifacts_root=tmp_path)
    assert paths.xbrl_root == tmp_path / "xbrl"
    assert paths.xml_cache_dir == tmp_path / "xbrl" / "xml"
    assert paths.default_prime_heads_path.name == "prime_heads.json"
    assert paths.default_subatomic_modifiers_path.name == "subatomic_modifiers.json"
    assert paths.default_token_lexicon_path.name == "token_lexicon.json"
    assert paths.default_atom_relations_path.name == "atom_relations.json"
    assert paths.default_relation_types_path.name == "relation_types.json"
    assert paths.default_geography_path.name == "geography_dag.json"
    assert paths.default_industries_path.name == "industries.json"

    paths.ensure_directories()
    assert paths.xml_cache_dir.exists()
    assert default_taxonomy_dir().name == "taxonomy"


def test_default_taxonomy_dir_is_package_anchored(tmp_path: Path) -> None:
    """Package data self-locates: the caller's root cannot move the taxonomy."""
    expected = PACKAGE_ROOT / ENGINE_DIR / XBRL_DIR / TAXONOMY_DIR
    assert resolve_xbrl_paths(repo_root=tmp_path).default_taxonomy_dir == expected
    assert expected.is_dir()


def test_taxonomy_archive_loads_from_an_arbitrary_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An installed copy in a bare directory sees the shipped taxonomies."""
    from edgar_sec.engine.xbrl.taxonomy.archive import (
        archived_taxonomies,
        load_slice,
    )

    monkeypatch.chdir(tmp_path)
    assert "us-gaap" in archived_taxonomies()
    assert load_slice("us-gaap", "2025")
