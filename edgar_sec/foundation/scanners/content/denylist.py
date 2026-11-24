"""Scanner flagging personal denylist literals in tracked text.
Flags a tracked text line containing a provisioned literal; with no
list provisioned, reports nothing. Exemptions: the denylist file
itself and the scanner mirror tests."""

from __future__ import annotations

import os
from pathlib import Path

from ..base import Scanner, ScannerFinding
from ..files import tracked_paths
from ..lines import finding

DENYLIST_ENV_VAR = "STARTER_DENYLIST_FILE"
DEFAULT_DENYLIST_PATH = Path("var/config/denylist.txt")

SCAN_SUFFIXES = (
    ".py",
    ".md",
    ".toml",
    ".yaml",
    ".yml",
    ".json",
    ".ts",
    ".tsx",
    ".js",
    ".mjs",
    ".sh",
    ".tmpl",
    ".txt",
)
SCAN_NAMES = frozenset({".gitignore"})

# The mirror tests seed a fake literal in their own source to pin
# behaviour; that source is not content under scan.
EXCLUDED_PREFIX = "tests/foundation/scanners/"


def _resolve_denylist(root: Path) -> Path | None:
    """The denylist in force: the env-named file, else the default."""
    raw = os.environ.get(DENYLIST_ENV_VAR)
    if raw:
        return Path(raw)
    default = root / DEFAULT_DENYLIST_PATH
    if default.is_file():
        return default
    return None


def _load_denylist(root: Path) -> list[str]:
    """The provisioned literals; empty when no list resolves."""
    denylist_path = _resolve_denylist(root)
    if denylist_path is None:
        return []
    try:
        lines = denylist_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    return [
        line.strip()
        for line in lines
        if line.strip() and not line.strip().startswith("#")
    ]


def _read_lines(path: Path) -> list[str] | None:
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return None


def _in_population(path: Path) -> bool:
    return path.suffix in SCAN_SUFFIXES or path.name in SCAN_NAMES


def _walk(root: Path) -> list[Path]:
    """Walk-mode candidates when no tracked listing is available."""
    found: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or not _in_population(path):
            continue
        parts = path.relative_to(root).parts
        if any(part.startswith(".") for part in parts[:-1]):
            continue
        found.append(path)
    return found


def population(root: Path) -> list[Path]:
    """Tracked text files, the scanner mirror tests excluded."""
    tracked = tracked_paths(root)
    if tracked is not None:
        candidates = [root / name for name in tracked]
    else:
        candidates = _walk(root)
    files: list[Path] = []
    for path in candidates:
        if not _in_population(path) or not path.is_file():
            continue
        relpath = path.relative_to(root).as_posix()
        if relpath.startswith(EXCLUDED_PREFIX):
            continue
        files.append(path)
    return files


def scan_tree(root: Path) -> list[ScannerFinding]:
    """Scan one tree root and return the denylist findings."""
    findings: list[ScannerFinding] = []
    literals = _load_denylist(root)
    if not literals:
        return findings
    denylist_path = _resolve_denylist(root)
    denylist_real = None
    if denylist_path is not None:
        try:
            denylist_real = denylist_path.resolve()
        except OSError:
            denylist_real = None
    for path in population(root):
        if denylist_real is not None:
            try:
                if path.resolve() == denylist_real:
                    continue
            except OSError:
                pass
        lines = _read_lines(path)
        if lines is None:
            continue
        relpath = path.relative_to(root).as_posix()
        for lineno, line in enumerate(lines, start=1):
            if any(literal in line for literal in literals):
                # Never include the literal or the line content here.
                findings.append(
                    finding(
                        "denylist",
                        relpath,
                        lineno,
                        "personal denylist literal present (content withheld)",
                        "Remove the literal; personal literals live only in"
                        " the untracked denylist file.",
                    )
                )
    return findings


def scan_denylist() -> list[ScannerFinding]:
    """Report denylist literals in the current tree's tracked text."""
    return scan_tree(Path.cwd())


SCANNER = Scanner(
    name="denylist",
    description="no personal denylist literals in tracked content",
    run=scan_denylist,
)
