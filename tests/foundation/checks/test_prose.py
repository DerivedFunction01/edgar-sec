"""Prose-only detection: comments, docstrings, and layout must not select tests."""

from __future__ import annotations

from pathlib import Path

from edgar_sec.foundation.checks.prose import (
    is_prose_only,
    normalized_dump,
    prose_only_python_files,
)


def test_normalized_dump_is_none_for_unparsable_text():
    assert normalized_dump("def broken(:") is None


def test_comment_edit_is_prose_only():
    assert is_prose_only("x = 1\n", "# explains x\nx = 1  # trailing\n")


def test_docstring_edit_is_prose_only():
    baseline = '"""Old prose."""\n\n\ndef f():\n    """Old."""\n    return 1\n'
    current = '"""New prose."""\n\n\ndef f():\n    """New."""\n    return 1\n'
    assert is_prose_only(baseline, current)


def test_docstring_removal_is_prose_only():
    baseline = '"""Prose."""\n\n\ndef f():\n    """Prose."""\n    return 1\n'
    assert is_prose_only(baseline, "def f():\n    return 1\n")


def test_class_and_async_docstrings_are_stripped():
    baseline = "class C:\n    'Old.'\n\n    async def m(self):\n        'Old.'\n        return 1\n"
    current = "class C:\n    'New.'\n\n    async def m(self):\n        'New.'\n        return 1\n"
    assert is_prose_only(baseline, current)


def test_logic_change_is_not_prose_only():
    assert not is_prose_only("return 1\n", "return 2\n")


def test_import_change_is_not_prose_only():
    assert not is_prose_only("import os\n", "import os\nimport sys\n")


def test_hash_inside_string_is_not_prose_only():
    assert not is_prose_only("MARKER = 'old'\n", "MARKER = 'new'\n")


def test_mid_body_string_is_not_a_docstring():
    baseline = "def f():\n    x = 1\n    'not a docstring'\n    return x\n"
    current = "def f():\n    x = 1\n    'changed'\n    return x\n"
    assert not is_prose_only(baseline, current)


def test_reordered_definitions_are_not_prose_only():
    baseline = "def a():\n    return 1\n\n\ndef b():\n    return 2\n"
    current = "def b():\n    return 2\n\n\ndef a():\n    return 1\n"
    assert not is_prose_only(baseline, current)


def test_prose_only_python_files_uses_git_baseline(tmp_path: Path):
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)

    src = tmp_path / "edgar_sec" / "pkg" / "mod.py"
    test = tmp_path / "tests" / "pkg" / "test_mod.py"
    for path, text in (
        (src, '"""Old."""\n\n\ndef f():\n    return 1\n'),
        (test, "def test_f():\n    assert True\n"),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=tmp_path, check=True)

    fresh = tmp_path / "edgar_sec" / "pkg" / "new.py"
    fresh.write_text("VALUE = 1\n", encoding="utf-8")
    src.write_text('"""New."""\n\n\ndef f():\n    return 1\n', encoding="utf-8")
    test.write_text(
        "# added a comment\ndef test_f():\n    assert True\n", encoding="utf-8"
    )

    from edgar_sec.foundation.checks.git_diff import get_git_status

    snapshot = get_git_status(tmp_path)
    assert "edgar_sec/pkg/new.py" in snapshot.python_sources
    assert prose_only_python_files(snapshot, tmp_path) == frozenset(
        {"edgar_sec/pkg/mod.py", "tests/pkg/test_mod.py"}
    )
