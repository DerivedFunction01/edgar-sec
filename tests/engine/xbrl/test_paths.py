"""Tests for XBRL artifact paths resolution."""

from pathlib import Path

from edgar_sec.engine.xbrl.paths import default_taxonomy_dir, resolve_xbrl_paths


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
