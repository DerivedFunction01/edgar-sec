"""Tests for static artifact path tree generation."""

from __future__ import annotations

from pathlib import Path

import pytest

from edgar_sec.tools.docgen.path_tree import render_path_tree, render_paths_tree


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


def test_delegated_paths_render_through_factory_and_defaults(
    tmp_path: Path,
) -> None:
    layout = _write_module(
        tmp_path,
        "layout",
        '"""Shared layout owners."""\n'
        "from dataclasses import dataclass\n"
        "from pathlib import Path\n"
        'MANIFEST_NAME = "manifest.jsonl"\n'
        'CASES_NAME = "cases"\n'
        "@dataclass(frozen=True)\n"
        "class ExternalPaths:\n"
        "    root: Path\n"
        "    manifest_filename: str = MANIFEST_NAME\n"
        "    cases_directory: str = CASES_NAME\n"
        "    @property\n"
        "    def manifest_path(self) -> Path:\n"
        "        return self.root / self.manifest_filename\n"
        "    @property\n"
        "    def cases_root(self) -> Path:\n"
        "        return self.root / self.cases_directory\n"
        "    def case_dir(self, case_id: str) -> Path:\n"
        "        return self.cases_root / case_id\n"
        "def external_paths(root, run_id):\n"
        '    return ExternalPaths(root / "review-runs" / run_id, MANIFEST_NAME)\n'
        "class StorePaths:\n"
        "    root: Path\n"
        "    def relation_dir(self, snapshot_id: str, relation: str) -> Path:\n"
        "        return self.root / snapshot_id / relation\n"
        "    def part_path(\n"
        "        self, snapshot_id: str, relation: str, part_index: int\n"
        "    ) -> Path:\n"
        "        return self.relation_dir(snapshot_id, relation) / (\n"
        '            f"part-{part_index:05d}.parquet"\n'
        "        )\n",
    )
    layout.with_name("paths.py").write_text(
        '"""Sample path layout."""\nfrom pathlib import Path\n'
        "from .layout import StorePaths, external_paths\n"
        'SOLVED_FILE = "solved_nodes.parquet"\n'
        "class SamplePaths:\n"
        "    artifacts_root: Path\n"
        "    @property\n"
        "    def dataset_root(self) -> Path:\n"
        '        return self.artifacts_root / "xbrl"\n'
        "    def external(self, run_id: str):\n"
        "        return external_paths(self.dataset_root, run_id)\n"
        "    def manifest_path(self, run_id: str) -> Path:\n"
        "        return self.external(run_id).manifest_path\n"
        "    def case_dir(self, run_id: str, accession: str) -> Path:\n"
        "        return self.external(run_id).case_dir(accession)\n"
        "    def case_solved_path(self, run_id: str, accession: str) -> Path:\n"
        "        return self.case_dir(run_id, accession) / SOLVED_FILE\n"
        "    @property\n"
        "    def snapshots_root(self) -> Path:\n"
        '        return self.dataset_root / "snapshots"\n'
        "    def relation_dir(self, snapshot_id: str, relation: str) -> Path:\n"
        "        return StorePaths(self.snapshots_root).relation_dir(\n"
        "            snapshot_id, relation\n"
        "        )\n"
        "    def part_path(\n"
        "        self, snapshot_id: str, relation: str, part_index: int\n"
        "    ) -> Path:\n"
        "        return StorePaths(self.snapshots_root).part_path(\n"
        "            snapshot_id, relation, part_index\n"
        "        )\n",
        encoding="utf-8",
    )

    result = render_paths_tree(layout.with_name("paths.py"))
    assert "review-runs/" in result
    assert "cases/" in result
    assert "{cases_directory}" not in result
    assert "manifest.jsonl" in result
    assert "{accession}/" in result
    assert "solved_nodes.parquet" in result
    assert "{relation}/" in result
    assert "part-{part_index}.parquet" in result


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
