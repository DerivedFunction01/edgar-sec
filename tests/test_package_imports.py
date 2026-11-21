"""Import every package: a package that cannot be imported is unusable, and nothing
else in the gate can tell that apart from untested.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

_ROOT = Path("edgar_sec")


def _packages() -> list[str]:
    """A directory counts when it holds a non-``__init__`` module, excluding layer markers."""
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
