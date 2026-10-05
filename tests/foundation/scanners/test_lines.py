"""The shared text-scanning helpers.
Every text scanner depends on these, so a regression here weakens several at once
rather than failing one test.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from edgar_sec.foundation.scanners import lines


def _build_repo(root: Path, files: dict[str, str]) -> None:
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


@pytest.fixture()
def synthetic_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_is_noise_recognises_comments_and_docstrings() -> None:
    assert lines.is_noise("# comment")
    assert lines.is_noise("   # indented comment")
    assert lines.is_noise('"""docstring"""')
    assert not lines.is_noise("value = 1")


def test_is_noise_ignores_a_hash_inside_code() -> None:
    assert not lines.is_noise('token = "#not-a-comment"')


def test_is_scanner_infrastructure_covers_scanners_and_tests() -> None:
    assert lines.is_scanner_infrastructure("edgar_sec/foundation/scanners/paths.py")
    assert lines.is_scanner_infrastructure("tests/foundation/test_x.py")
    assert not lines.is_scanner_infrastructure("edgar_sec/engine/thing.py")


def test_matches_allowed_handles_file_and_directory_prefixes() -> None:
    prefixes = ("edgar_sec/foundation/text/dates.py", "edgar_sec/engine/tables/")
    assert lines.matches_allowed("edgar_sec/foundation/text/dates.py", prefixes)
    assert lines.matches_allowed("edgar_sec/engine/tables/toc.py", prefixes)
    assert not lines.matches_allowed("edgar_sec/engine/thing.py", prefixes)


def test_matches_allowed_normalises_windows_separators() -> None:
    assert lines.matches_allowed(
        "edgar_sec\\engine\\tables\\toc.py", ("edgar_sec/engine/tables/",)
    )


def test_scan_text_rule_reports_matches_with_line_numbers(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/a.py": "ok = 1\nBAD = 2\n",
            "edgar_sec/b.py": "BAD = 3\n",
        },
    )

    def rule(path: str, number: int, line: str):
        return (
            lines.finding("demo", path, number, "bad line", "fix it")
            if "BAD" in line
            else None
        )

    findings = lines.scan_text_rule(rule)
    assert [(f.path, f.line) for f in findings] == [
        ("edgar_sec/a.py", 2),
        ("edgar_sec/b.py", 1),
    ]


def test_scan_text_rule_skips_noise_allowlist_and_skip_list(
    synthetic_repo: Path,
) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/allowed/thing.py": "BAD = 1\n",
            "edgar_sec/skipme.py": "BAD = 1\n",
            "edgar_sec/ok.py": "# BAD = 1\n",
        },
    )

    def rule(path: str, number: int, line: str):
        return (
            lines.finding("demo", path, number, "bad line", "fix it")
            if "BAD" in line
            else None
        )

    findings = lines.scan_text_rule(
        rule, prefixes=("edgar_sec/allowed/",), skip=("edgar_sec/skipme.py",)
    )
    assert findings == []


def test_iter_source_lines_skips_undecodable_files(synthetic_repo: Path) -> None:
    path = synthetic_repo / "edgar_sec" / "binary.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\xff\xfe\x00bad")
    collected = list(lines.iter_source_lines())
    assert all(p != "edgar_sec/binary.py" for p, _, _ in collected)
