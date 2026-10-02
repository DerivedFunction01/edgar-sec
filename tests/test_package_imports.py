"""Package import smoke test.

`engine.tables.ascii_html` was dead for its entire lifetime while the suite
passed: no test imported it, so its five unresolvable imports were invisible to
1,248 green tests. A package that cannot be imported is not "untested", it is
*unusable*, and nothing else in the gate could see the difference. This test is
that detector: importing every package is the cheapest possible proof that the
tree is load-bearing.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

_ROOT = Path("edgar_sec")


def _packages() -> list[str]:
    """Every directory under ``edgar_sec`` that owns python modules.

    A directory counts when it holds at least one non-``__init__`` module, which
    excludes the bare layer markers that exist only to make a directory a
    package.
    """
    found: set[str] = set()
    for path in _ROOT.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        directory = path.parent
        if path.name != "__init__.py" or any(
            (directory / name).suffix == ".py" and name != "__init__.py"
            for name in {p.name for p in directory.glob("*.py")}
        ):
            found.add(str(directory))
    return sorted(found)


@pytest.mark.parametrize("package", _packages(), ids=lambda p: p)
def test_package_imports(package: str) -> None:
    """Every package under edgar_sec must import without raising."""
    module = package.replace("/", ".")
    importlib.import_module(module)
