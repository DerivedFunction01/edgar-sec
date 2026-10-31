"""The uncompiled-regex scanner.
Both directions are pinned: an uncompiled re.search is caught, and a compiled
constant's method call is left alone.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from edgar_sec.foundation.scanners import uncompiled_regex


def _build_repo(root: Path, files: dict[str, str]) -> None:
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


@pytest.fixture()
def synthetic_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_flags_uncompiled_search(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/pipelines/thing/job.py": (
                'import re\nmatch = re.search(r"foo", text)\n'
            )
        },
    )
    findings = uncompiled_regex.scan_uncompiled_regex()
    assert [(f.path, f.line) for f in findings] == [
        ("edgar_sec/pipelines/thing/job.py", 2)
    ]


def test_flags_uncompiled_fullmatch(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/pipelines/thing/job.py": (
                'import re\nok = re.fullmatch(r"[0-9]+", value) is not None\n'
            )
        },
    )
    assert uncompiled_regex.scan_uncompiled_regex()


def test_allows_compiled_constant(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/pipelines/thing/job.py": (
                'import re\n_RE = re.compile(r"foo")\nmatch = _RE.search(text)\n'
            )
        },
    )
    assert uncompiled_regex.scan_uncompiled_regex() == []


def test_ignores_tests(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {"tests/test_thing.py": 'import re\nmatch = re.search(r"foo", text)\n'},
    )
    assert uncompiled_regex.scan_uncompiled_regex() == []
