"""Tests for the denylist scanner's provisioning and withholding."""

from __future__ import annotations

from pathlib import Path

import pytest

from edgar_sec.foundation.scanners import ALL_SCANNERS
from edgar_sec.foundation.scanners.base import SEVERITY_ERROR
from edgar_sec.foundation.scanners.content import denylist
from edgar_sec.foundation.scanners.content.denylist import scan_tree

LITERAL = "Zxqwv Testperson"
ENV_VAR = "STARTER_DENYLIST_FILE"


def _write(root: Path, relpath: str, text: str) -> None:
    path = root / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture(autouse=True)
def _no_provisioning(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV_VAR, raising=False)


def test_unprovisioned_reports_nothing(tmp_path: Path) -> None:
    _write(tmp_path, "note.md", "plain text\n")
    assert scan_tree(tmp_path) == []


def test_env_provisioned_literal_is_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path, "list.txt", LITERAL + "\n")
    _write(tmp_path, "note.md", f"ask {LITERAL} about it\n")
    monkeypatch.setenv(ENV_VAR, str(tmp_path / "list.txt"))
    findings = scan_tree(tmp_path)
    errors = [f for f in findings if f.severity == SEVERITY_ERROR]
    assert len(errors) == 1
    assert errors[0].path == "note.md"
    assert errors[0].line == 1
    for finding in findings:
        assert LITERAL not in str(finding)


def test_denylist_file_itself_is_never_scanned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path, "list.txt", LITERAL + "\n")
    monkeypatch.setenv(ENV_VAR, str(tmp_path / "list.txt"))
    assert scan_tree(tmp_path) == []


def test_unreadable_env_path_does_not_fall_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path, "var/config/denylist.txt", LITERAL + "\n")
    _write(tmp_path, "note.md", f"ask {LITERAL} about it\n")
    monkeypatch.setenv(ENV_VAR, str(tmp_path / "missing.txt"))
    assert scan_tree(tmp_path) == []


def test_default_path_provisioned(tmp_path: Path) -> None:
    _write(tmp_path, "var/config/denylist.txt", LITERAL + "\n")
    _write(tmp_path, "note.md", f"ask {LITERAL} about it\n")
    findings = scan_tree(tmp_path)
    errors = [f for f in findings if f.severity == SEVERITY_ERROR]
    assert len(errors) == 1


def test_scanner_is_registered() -> None:
    assert denylist.SCANNER in ALL_SCANNERS
    assert "denylist" in {scanner.name for scanner in ALL_SCANNERS}
