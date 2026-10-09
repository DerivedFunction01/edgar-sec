"""Tests for static artifact path tree generation."""

from __future__ import annotations

from pathlib import Path

import pytest

from edgar_sec.tools.path_tree import render_path_tree, render_paths_tree


def _write_module(root: Path, module: str, content: str) -> Path:
    path = root / "edgar_sec" / "pipelines" / "sample" / f"{module}.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_module_sentinel_disables_tree(tmp_path: Path) -> None:
    source = _write_module(
        tmp_path,
        "paths",
        '"""Paths.\n\n:no-path-tree:\n"""\nfrom pathlib import Path\n'
        "class SamplePaths:\n"
        "    root: Path\n"
        "    def file(self) -> Path:\n"
        '        return self.root / "file.json"\n',
    )

    assert render_paths_tree(source) == "No published artifact paths."


def test_method_sentinel_omits_path_target(tmp_path: Path) -> None:
    source = _write_module(
        tmp_path,
        "paths",
        '"""Paths."""\nfrom pathlib import Path\n'
        "class SamplePaths:\n"
        "    root: Path\n"
        "    def visible(self) -> Path:\n"
        '        """Visible output."""\n'
        '        return self.root / "visible.json"\n'
        "    def internal(self) -> Path:\n"
        '        """Internal helper. :no-docgen:"""\n'
        '        return self.root / "internal.json"\n',
    )

    result = render_paths_tree(source)
    assert "visible.json  # Visible output." in result
    assert "internal.json" not in result


def test_imported_constants_and_helpers_are_resolved_from_ast(tmp_path: Path) -> None:
    helper = _write_module(
        tmp_path,
        "layout",
        '"""Shared layout constants."""\nfrom pathlib import Path\n'
        'STAGING_DIR = "queue"\n'
        "def staged_path(root, run_id):\n"
        "    return root / STAGING_DIR / run_id\n",
    )
    helper.write_text(
        helper.read_text(encoding="utf-8") + "\nclass ExternalPaths:\n"
        "    root: Path\n"
        "    def foreign(self) -> Path:\n"
        '        return self.root / "foreign.json"\n',
        encoding="utf-8",
    )
    helper.with_name("paths.py").write_text(
        '"""Sample path layout."""\nfrom pathlib import Path\n'
        "from .layout import ExternalPaths, staged_path\n"
        'OBJECTS_DIR = "objects"\n'
        "class SamplePaths:\n"
        "    artifacts_root: Path\n"
        "    @property\n"
        "    def root(self) -> Path:\n"
        "        return self.artifacts_root / OBJECTS_DIR\n"
        "    def run_dir(self, run_id: str) -> Path:\n"
        "        return staged_path(self.root, run_id)\n"
        "    def numbered(self, chunk_id: int) -> Path:\n"
        '        return self.root / f"chunk_{chunk_id:04d}.parquet"\n',
        encoding="utf-8",
    )

    result = render_paths_tree(helper.with_name("paths.py"))
    assert "{artifacts_root}/" in result
    assert "objects/" in result
    assert "queue/" in result
    assert "{run_id}/" in result
    assert "chunk_{chunk_id}.parquet" in result
    assert "foreign.json" not in result

    helper.write_text(
        helper.read_text(encoding="utf-8").replace('"queue"', '"holding"'),
        encoding="utf-8",
    )
    refreshed = render_paths_tree(helper.with_name("paths.py"))
    assert "holding/" in refreshed
    assert "queue/" not in refreshed


def test_tree_uses_stable_branch_connectors() -> None:
    result = render_path_tree(
        [
            ("{artifacts_root}/snapshots/{id}/data.parquet", "Payload."),
            ("{artifacts_root}/plans/{id}/plan.json", "Manifest."),
        ]
    )

    assert result.startswith("```text\n{artifacts_root}/\n├── plans/")
    assert "└── snapshots/" in result
    assert result.endswith("```")


def test_unresolved_path_requires_an_explicit_sentinel(tmp_path: Path) -> None:
    source = _write_module(
        tmp_path,
        "paths",
        '"""Paths."""\nfrom pathlib import Path\n'
        "class SamplePaths:\n"
        "    root: Path\n"
        "    def path(self) -> Path:\n"
        "        return unknown_path(self.root)\n",
    )

    with pytest.raises(ValueError, match="SamplePaths.path"):
        render_paths_tree(source)
