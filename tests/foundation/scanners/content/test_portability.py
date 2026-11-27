"""Tests for the portability scanner's legs and provisioning."""

from __future__ import annotations

from pathlib import Path

import pytest

from edgar_sec.foundation.scanners import ALL_SCANNERS
from edgar_sec.foundation.scanners.content.portability import scan_tree

ENV_VAR = "STARTER_REPO_SET_FILE"


def _write(root: Path, relpath: str, text: str) -> None:
    path = root / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture(autouse=True)
def _no_provisioning(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV_VAR, raising=False)


def test_registered_in_all_scanners() -> None:
    assert any(s.name == "portability" for s in ALL_SCANNERS)


def test_clean_text_reports_nothing(tmp_path: Path) -> None:
    _write(tmp_path, "note.md", "runs on the parallel compute venue\n")
    assert scan_tree(tmp_path) == []


def test_absolute_home_path_is_an_error(tmp_path: Path) -> None:
    _write(tmp_path, "note.md", "see " + "/home" + "/someone/tree\n")
    findings = scan_tree(tmp_path)
    assert len(findings) == 1
    assert findings[0].path == "note.md"
    assert "portability/abs-path" in findings[0].message
    assert "/home" not in findings[0].message


def test_specific_plan_file_reference_is_an_error(tmp_path: Path) -> None:
    _write(tmp_path, "note.md", "the plan (`.plans/2026-01-01-x.md`)\n")
    findings = scan_tree(tmp_path)
    assert len(findings) == 1
    assert "portability/untracked-ref" in findings[0].message


def test_generic_plans_mention_passes(tmp_path: Path) -> None:
    _write(tmp_path, "note.md", "plans live in a `.plans/` folder\n")
    assert scan_tree(tmp_path) == []


def test_repo_ref_leg_needs_provisioning(tmp_path: Path) -> None:
    _write(tmp_path, "mod.py", "X = 'other-repo'\n")
    assert scan_tree(tmp_path) == []


def test_repo_ref_in_code_is_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path, "set.txt", "other-repo\n")
    _write(tmp_path, "mod.py", "X = 'other-repo'\n")
    _write(tmp_path, "note.md", "docs may name other-repo\n")
    monkeypatch.setenv(ENV_VAR, str(tmp_path / "set.txt"))
    findings = scan_tree(tmp_path)
    assert len(findings) == 1
    assert findings[0].path == "mod.py"
    assert "portability/external-repo-ref" in findings[0].message


def test_exception_directive_in_non_registry_file_is_an_error(
    tmp_path: Path,
) -> None:
    marker = "portability" + "-exception:"
    _write(tmp_path, "note.md", f"{marker} /home/x — a reason\n")
    findings = scan_tree(tmp_path)
    assert any(
        "portability/exception-misuse" in f.message for f in findings
    )
