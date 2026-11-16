"""Pins for the viewer mtime home (Wave 2B).
The stat helper lives in ``loaders``; ``tree`` binds it.
"""

from __future__ import annotations

from pathlib import Path

from edgar_sec.apps.viewer import loaders, tree


def test_binding_is_the_loaders_home() -> None:
    assert tree._mtime_ns is loaders._mtime_ns


def test_mtime_verdicts(tmp_path: Path) -> None:
    target = tmp_path / "entry.txt"
    target.write_text("x", encoding="utf-8")
    assert loaders._mtime_ns(target) == target.stat().st_mtime_ns
    assert loaders._mtime_ns(tmp_path / "missing") == 0
