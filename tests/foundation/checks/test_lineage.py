from __future__ import annotations

from pathlib import Path

from edgar_sec.foundation.checks.lineage import (
    LineageGraph,
    find_mirror_test,
    path_to_module,
    resolve_relative_import,
)


def test_path_to_module():
    assert path_to_module("edgar_sec/domain/identity.py") == "edgar_sec.domain.identity"
    assert (
        path_to_module("edgar_sec/domain/forms/__init__.py") == "edgar_sec.domain.forms"
    )
    assert (
        path_to_module("tests/domain/test_identity.py") == "tests.domain.test_identity"
    )


def test_resolve_relative_import():
    # from .models import ... inside edgar_sec.domain.forms.common.aliases (pkg is edgar_sec.domain.forms.common)
    mod = "edgar_sec.domain.forms.common.aliases"
    assert (
        resolve_relative_import(mod, 1, "models")
        == "edgar_sec.domain.forms.common.models"
    )
    # from ..common.aliases import ... inside edgar_sec.domain.forms.quarterly.evidence
    mod2 = "edgar_sec.domain.forms.quarterly.evidence"
    assert (
        resolve_relative_import(mod2, 2, "common.aliases")
        == "edgar_sec.domain.forms.common.aliases"
    )


def test_find_mirror_test(tmp_path: Path):
    src = tmp_path / "edgar_sec" / "domain" / "foo.py"
    test = tmp_path / "tests" / "domain" / "test_foo.py"
    src.parent.mkdir(parents=True)
    test.parent.mkdir(parents=True)
    src.write_text("x = 1")
    test.write_text("def test_x(): pass")

    mirror = find_mirror_test("edgar_sec/domain/foo.py", tmp_path)
    assert mirror == "tests/domain/test_foo.py"


def test_lineage_graph_reverse_transitive_resolution(tmp_path: Path):
    root = tmp_path
    sec_dir = root / "edgar_sec" / "pkg"
    sec_dir.mkdir(parents=True)
    test_dir = root / "tests" / "pkg"
    test_dir.mkdir(parents=True)

    file_a = sec_dir / "mod_a.py"
    file_b = sec_dir / "mod_b.py"
    test_b = test_dir / "test_mod_b.py"

    file_a.write_text("VAL = 42\n")
    file_b.write_text("from edgar_sec.pkg.mod_a import VAL\n")
    test_b.write_text(
        "from edgar_sec.pkg.mod_b import VAL\ndef test_b(): assert VAL == 42\n"
    )

    graph = LineageGraph(repo_root=root, cache_path=Path("cache.json"))
    graph.sync_files([file_a, file_b, test_b])

    res = graph.resolve_tests(
        changed_sources=("edgar_sec/pkg/mod_a.py",),
        changed_tests=(),
        changed_conftests=(),
    )

    assert "tests/pkg/test_mod_b.py" in res.test_files
    reasons = res.reasons["tests/pkg/test_mod_b.py"]
    assert any("transitive_dependency" in r for r in reasons)


def test_conftest_scoped_invalidation(tmp_path: Path):
    root = tmp_path
    test_dir_a = root / "tests" / "sub_a"
    test_dir_b = root / "tests" / "sub_b"
    test_dir_a.mkdir(parents=True)
    test_dir_b.mkdir(parents=True)

    conftest_a = test_dir_a / "conftest.py"
    conftest_a.write_text("# fixtures\n")
    test_a = test_dir_a / "test_a.py"
    test_a.write_text("def test_a(): pass\n")

    test_b = test_dir_b / "test_b.py"
    test_b.write_text("def test_b(): pass\n")

    graph = LineageGraph(repo_root=root, cache_path=Path("cache.json"))
    res = graph.resolve_tests(
        changed_sources=(),
        changed_tests=(),
        changed_conftests=("tests/sub_a/conftest.py",),
    )

    assert "tests/sub_a/test_a.py" in res.test_files
    assert "tests/sub_b/test_b.py" not in res.test_files
