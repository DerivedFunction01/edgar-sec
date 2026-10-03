"""Tests for the regex-alternations scanner.

The scanner is the only thing keeping `foundation.regex.builder` important, so
these tests pin both directions: a hand-crafted 3+ branch alternation is caught,
and the legitimate two-branch structural groups are left alone.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from edgar_sec.foundation.scanners import regex_alternations


def _build_repo(root: Path, files: dict[str, str]) -> None:
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


@pytest.fixture()
def synthetic_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_flags_three_branch_group(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {"edgar_sec/engine/thing.py": 'PATTERN = r"(?:alpha|beta|gamma)"\n'},
    )
    findings = regex_alternations.scan_regex_alternations()
    assert [f.path for f in findings] == ["edgar_sec/engine/thing.py"]


def test_flags_quoted_pipe_chain(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {"edgar_sec/engine/thing.py": 'CHOICES = "alpha|beta|gamma|delta"\n'},
    )
    assert regex_alternations.scan_regex_alternations()


def test_allows_two_branch_group(synthetic_repo: Path) -> None:
    """Two branches carry no ordering hazard, so they are not this rule's business."""
    _build_repo(
        synthetic_repo,
        {"edgar_sec/engine/thing.py": 'YES_NO = r"\\b(?:yes|no)\\b"\n'},
    )
    assert regex_alternations.scan_regex_alternations() == []


def test_allows_alternation_built_through_the_dsl(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                "from edgar_sec.foundation.regex.builder import build_alternation\n"
                "PATTERN = build_alternation(['alpha', 'beta', 'gamma'])\n"
            )
        },
    )
    assert regex_alternations.scan_regex_alternations() == []


def test_allows_regex_package_and_text_vocabulary(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/foundation/regex/thing.py": 'P = r"(?:a|b|c)"\n',
            "edgar_sec/foundation/text/thing.py": 'P = r"(?:a|b|c)"\n',
        },
    )
    assert regex_alternations.scan_regex_alternations() == []


def test_ignores_commented_out_alternation(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {"edgar_sec/engine/thing.py": '# old: r"(?:alpha|beta|gamma)"\n'},
    )
    assert regex_alternations.scan_regex_alternations() == []


def test_ignores_tests(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {"tests/test_thing.py": 'P = r"(?:alpha|beta|gamma)"\n'},
    )
    assert regex_alternations.scan_regex_alternations() == []


def test_hint_points_at_the_builder(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {"edgar_sec/engine/thing.py": 'P = r"(?:alpha|beta|gamma)"\n'},
    )
    hint = regex_alternations.scan_regex_alternations()[0].hint
    assert "build_alternation" in hint
