"""Cross-layer contract: nothing reachable offline may import the HTTP client.

Proved by an AST walk over each package's modules, not by grep: a grep misses
re-exports, alias imports, and function-local imports.
"""

from __future__ import annotations

import ast
from collections import deque
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parent.parent / "edgar_sec"
FORBIDDEN = "edgar_sec.infra.sec_http"

# metadata_sync is deliberately absent: it is the network phase, and the
# sensitivity test below uses it to prove the walk finds a real dependency.
# edgar_sec.apps is here because a read-only tool browsing artifacts a network
# pipeline produced has more reason to reach for the client, not less.
OFFLINE_PACKAGES = (
    "edgar_sec.pipelines.filing_catalog",
    "edgar_sec.engine.selection",
    "edgar_sec.domain.taxonomy",
    "edgar_sec.domain.filing_catalog",
    "edgar_sec.apps.viewer",
)


def modules_in_package(package: str) -> set[str]:
    """Every module in a package and its nested packages, as dotted names.

    Includes each ``__init__``, since a re-export there is a real escape hatch.
    Expanding iteratively avoids re-globbing forever on a package's own init.
    """
    found: set[str] = set()
    pending = [package]
    while pending:
        current = pending.pop()
        if current in found:
            continue
        found.add(current)
        directory = PACKAGE_ROOT / current.removeprefix("edgar_sec.").replace(".", "/")
        for path in directory.rglob("*.py"):
            parts = list(path.relative_to(PACKAGE_ROOT).with_suffix("").parts)
            if parts and parts[-1] == "__init__":
                parts.pop()
                pending.append(".".join(["edgar_sec", *parts]))
            else:
                found.add(".".join(["edgar_sec", *parts]))
    return found


def _module_path(module: str) -> Path | None:
    """Resolve a dotted ``edgar_sec`` module name to a file on disk."""
    if not module.startswith("edgar_sec."):
        return None
    relative = module[len("edgar_sec.") :].replace(".", "/")
    for candidate in (
        PACKAGE_ROOT / f"{relative}.py",
        PACKAGE_ROOT / relative / "__init__.py",
    ):
        if candidate.is_file():
            return candidate
    return None


def _imports_in(path: Path) -> list[str]:
    """Every ``edgar_sec`` name this file imports, at any nesting depth.

    ``ast.walk`` so a function-local import is still found.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            # A relative import stays inside its own package, and every module
            # of that package is already an entry point or already reached.
            if node.level or not node.module:
                continue
            if node.module.startswith("edgar_sec"):
                found.append(node.module)
    return found


def reachable_modules(roots: set[str]) -> set[str]:
    """Every ``edgar_sec`` module importable from ``roots``, transitively."""
    seen: set[str] = set()
    queue = deque(sorted(roots))
    while queue:
        current = queue.popleft()
        if current in seen:
            continue
        path = _module_path(current)
        if path is None:
            continue
        seen.add(current)
        queue.extend(_imports_in(path))
    return seen


def http_reachable(package: str) -> set[str]:
    reachable = reachable_modules(modules_in_package(package))
    return {
        module
        for module in reachable
        if module == FORBIDDEN or module.startswith(f"{FORBIDDEN}.")
    }


@pytest.mark.parametrize("package", OFFLINE_PACKAGES)
def test_no_http_client_is_reachable_from_an_offline_package(package: str) -> None:
    offenders = http_reachable(package)
    assert offenders == set(), (
        f"{package} can reach the HTTP client via {sorted(offenders)}; it must"
        " never construct a request"
    )


def test_the_walk_actually_resolves_modules() -> None:
    """Guard the guard: a resolver that finds nothing makes every test above vacuous."""
    package = "edgar_sec.pipelines.filing_catalog"
    roots = modules_in_package(package)
    assert len(roots) >= 8, f"package expansion is broken: {sorted(roots)}"

    reachable = reachable_modules(roots)
    assert len(reachable) > 20
    assert any(module.startswith("edgar_sec.infra.storage") for module in reachable), (
        "the walk did not reach the storage layer the pipeline depends on"
    )
    assert any(
        module.startswith("edgar_sec.engine.selection") for module in reachable
    ), "the policy planner did not reach the selection engine"


def test_the_walk_follows_a_function_local_import() -> None:
    """A dependency hidden inside a function body is the shape a naive scanner misses."""
    reachable = reachable_modules({"edgar_sec.pipelines.filing_catalog.discovery"})
    assert "edgar_sec.infra.storage.duckdb" in reachable


def test_the_fetching_pipeline_is_still_reachable_from_the_http_client() -> None:
    """Sensitivity check: if this fails, every offline assertion above is vacuous."""
    offenders = http_reachable("edgar_sec.pipelines.metadata_sync")
    assert offenders, (
        "the network pipeline no longer reaches the client; the walk is broken"
    )
