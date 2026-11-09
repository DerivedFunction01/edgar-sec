"""Scanner detecting production references to the test tree.

Flags a `tests` path component or a `tests` import in layers 0-5: production
data lives in the package or the workspace, never under `tests/`.
"""

from __future__ import annotations

from pathlib import Path

from .base import Scanner, ScannerFinding
from .files import discover_python_files

_EXEMPT_PREFIXES = (
    "tests/",
    "edgar_sec/tools/",
    "edgar_sec/foundation/checks/",
)
_EXEMPT_FILES = {
    "check.py",
    "run.py",
    # Owns the fixture-corpus anchor: the review pipeline's bundle corpora
    # are fixture data in the checkout tree, named by registry stem there.
    "edgar_sec/pipelines/xbrl_review/bundles.py",
}
_NEEDLES = (
    '"tests"',
    "'tests'",
    '"tests/',
    "'tests/",
    "from tests",
    "import tests",
)


def scan_test_tree_paths() -> list[ScannerFinding]:
    """Ensure production code neither paths into nor imports the test tree."""
    findings: list[ScannerFinding] = []

    for path_str in discover_python_files():
        if (
            path_str in _EXEMPT_FILES
            or path_str.startswith(_EXEMPT_PREFIXES)
            or "scanners/" in path_str
        ):
            continue
        path = Path(path_str)
        if not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue

        for idx, line in enumerate(content.splitlines(), start=1):
            if any(needle in line for needle in _NEEDLES):
                findings.append(
                    ScannerFinding(
                        scanner="test-tree-paths",
                        source="static",
                        path=path_str,
                        line=idx,
                        message="Production reference to the test tree found",
                        hint="Keep production data in the package or the workspace.",
                    )
                )
    return findings


SCANNER = Scanner(
    name="test-tree-paths",
    description="scan Python files for production references to the test tree",
    run=scan_test_tree_paths,
)
