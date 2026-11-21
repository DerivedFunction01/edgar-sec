"""The test-tree-paths scanner.
Production references are caught in both shapes (path component and import);
the gate machinery that owns the test tree is left alone.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from edgar_sec.foundation.scanners import test_tree_paths


def _build_repo(root: Path, files: dict[str, str]) -> None:
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


@pytest.fixture()
def synthetic_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_flags_a_tests_path_component(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing/loader.py": (
                'REGISTRY = ROOT / "tests" / "fixtures" / "seed.json"\n'
            )
        },
    )
    findings = test_tree_paths.scan_test_tree_paths()
    assert [(f.path, f.line) for f in findings] == [
        ("edgar_sec/engine/thing/loader.py", 1)
    ]


def test_flags_a_tests_import(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {"edgar_sec/pipelines/thing/job.py": "from tests.support import rows\n"},
    )
    assert test_tree_paths.scan_test_tree_paths()


def test_no_file_exemptions_for_production_modules(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/pipelines/xbrl_review/bundles.py": (
                'SEGMENTS = ("tests", "fixtures", "xbrl")\n'
            ),
            "edgar_sec/pipelines/xbrl_review/other.py": (
                'SEGMENTS = ("tests", "fixtures", "xbrl")\n'
            ),
        },
    )
    findings = test_tree_paths.scan_test_tree_paths()
    assert [(f.path, f.line) for f in findings] == [
        ("edgar_sec/pipelines/xbrl_review/bundles.py", 1),
        ("edgar_sec/pipelines/xbrl_review/other.py", 1),
    ]


def test_allows_gate_machinery_and_tools(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/foundation/checks/lineage.py": 'PARTS = ["tests", "x"]\n',
            "edgar_sec/tools/eval/run.py": 'ROOT = REPO / "tests" / "fixtures"\n',
            "edgar_sec/engine/thing/loader.py": 'NAME = "testsets"\n',
        },
    )
    assert test_tree_paths.scan_test_tree_paths() == []
