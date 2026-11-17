"""Tests for root README sentinel synchronization.

Offline rendering checks over synthetic repository trees.
"""

from __future__ import annotations

from pathlib import Path

from edgar_sec.tools.docgen.root_readme import (
    ENTRYPOINTS_END,
    ENTRYPOINTS_START,
    GATE_END,
    GATE_START,
    LAYERS_END,
    LAYERS_START,
    render_entrypoints,
    render_gate,
    render_layers,
    sync_root_readme,
)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _synthetic_repo(root: Path) -> None:
    _write(
        root / "pyproject.toml",
        '[project]\nname = "x"\n\n[project.scripts]\n'
        'demo = "edgar_sec.foundation.cli:main"\n',
    )
    _write(
        root / "check.py",
        '"""Root validation gate."""\n\nimport argparse\n\n\n'
        "def main() -> None:\n"
        "    parser = argparse.ArgumentParser()\n"
        '    parser.add_argument("--fast", action="store_true", help="quick check")\n'
        '    parser.add_argument("paths", nargs="*")\n',
    )
    _write(root / "run.py", '"""Root interactive launcher."""\n')
    _write(root / "edgar_sec" / "foundation" / "__init__.py", "")
    _write(
        root / "edgar_sec" / "foundation" / "README.md",
        "# `edgar_sec/foundation` — Layer 0: primitives\n",
    )
    _write(root / "edgar_sec" / "foundation" / "cli.py", '"""Foundation CLI."""\n')
    _write(root / "edgar_sec" / "foundation" / "checks" / "__init__.py", "")
    _write(root / "edgar_sec" / "foundation" / "checks" / "README.md", "# checks\n")


def test_render_layers_lists_subpackages_with_links(tmp_path: Path) -> None:
    _synthetic_repo(tmp_path)
    result = render_layers(tmp_path)
    assert "| 0 — `foundation/` | primitives |" in result
    assert "[`checks`](edgar_sec/foundation/checks/README.md)" in result


def test_render_gate_extracts_flags_and_positional(tmp_path: Path) -> None:
    _synthetic_repo(tmp_path)
    result = render_gate(tmp_path)
    assert "| `--fast` | quick check |" in result
    assert "| `paths` (positional) | — |" in result


def test_render_entrypoints_reads_pyproject_scripts(tmp_path: Path) -> None:
    _synthetic_repo(tmp_path)
    result = render_entrypoints(tmp_path)
    assert "| `demo` | `edgar_sec.foundation.cli:main` | Foundation CLI. |" in result
    assert "| `run.py` | repo root | Root interactive launcher. |" in result


def test_sync_root_readme_replaces_stale_and_is_idempotent(tmp_path: Path) -> None:
    _synthetic_repo(tmp_path)
    readme = tmp_path / "README.md"
    _write(
        readme,
        "# x\n\n"
        f"{LAYERS_START}\nstale\n{LAYERS_END}\n\n"
        f"{GATE_START}\nstale\n{GATE_END}\n\n"
        f"{ENTRYPOINTS_START}\nstale\n{ENTRYPOINTS_END}\n",
    )
    in_sync, _ = sync_root_readme(readme, tmp_path, apply=False)
    assert in_sync is False
    in_sync, _ = sync_root_readme(readme, tmp_path, apply=True)
    assert in_sync is False
    assert "stale" not in readme.read_text(encoding="utf-8")
    in_sync, text = sync_root_readme(readme, tmp_path, apply=False)
    assert in_sync is True
    assert text == readme.read_text(encoding="utf-8")
