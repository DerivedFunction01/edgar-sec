"""Tests for XBRL artifact paths resolution."""

from pathlib import Path

from edgar_sec.engine.xbrl.paths import resolve_xbrl_paths


def test_resolve_xbrl_paths(tmp_path: Path) -> None:
    """Verify artifact directory and Parquet path generation."""
    paths = resolve_xbrl_paths(artifacts_root=tmp_path)
    assert paths.xbrl_root == tmp_path / "xbrl"
    assert paths.linkbases_dir == tmp_path / "xbrl" / "linkbases"
    assert (
        paths.default_linkbases_path
        == tmp_path / "xbrl" / "linkbases" / "linkbases.parquet"
    )
    assert (
        paths.linkbase_parquet_path("seed")
        == tmp_path / "xbrl" / "linkbases" / "seed_linkbases.parquet"
    )
    assert paths.default_prime_heads_path.name == "prime_heads.json"
    assert paths.default_subatomic_modifiers_path.name == "subatomic_modifiers.json"
    assert paths.default_typed_relations_path.name == "typed_relations.json"
    assert paths.default_geography_path.name == "geography_dag.json"
    assert paths.default_industries_path.name == "industries.json"

    paths.ensure_directories()
    assert paths.linkbases_dir.exists()
    assert paths.xml_cache_dir.exists()
