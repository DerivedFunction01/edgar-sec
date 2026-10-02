"""Cross-layer contract: nothing reachable offline may import the HTTP client.

Phase 2 is an offline phase. The plan's gate requires this to be *proved*, not
asserted, and proved by an AST walk rather than a grep: a grep for
``sec_http`` misses a re-export, an alias import, and a function-local import,
all three of which are real ways a network dependency creeps in.

Importing a package does not import its submodules, so each package is expanded
to its own modules and the walk starts from every one of them. Walking from the
``__init__`` alone would resolve a single docstring and pass vacuously.

This test lives at the root of the test tree rather than mirroring a module
because the invariant spans four packages -- the catalog pipeline, the selection
engine, and the two domain packages -- and a mirrored test would have to be
duplicated in each to say something weaker.
"""

from __future__ import annotations

import ast
from collections import deque
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parent.parent / "edgar_sec"
FORBIDDEN = "edgar_sec.infra.sec_http"

# The packages Stage 2 introduced, plus the Layer 5 apps. Phase 1's
# metadata_sync pipeline is deliberately absent: it *is* the network phase, and
# the last test here uses it to prove the walk is sensitive enough to find a
# dependency that does exist.
#
# ``edgar_sec.apps`` earns its place for a different reason than the Phase 2
# packages. A viewer browses artifacts that a *network* pipeline produced, so the
# temptation to reach for the client is structurally higher here, not lower. It
# reads what was already fetched; re-fetching would be both wrong and a way for
# a read-only tool to acquire a network surface.
OFFLINE_PACKAGES = (
    "edgar_sec.pipelines.filing_catalog",
    "edgar_sec.engine.selection",
    "edgar_sec.domain.taxonomy",
    "edgar_sec.domain.filing_catalog",
    "edgar_sec.apps.viewer",
)


# Every module in a package, as dotted names. A package ``__init__`` is included:
# it is a module like any other and a re-export in it would be a real escape.
def modules_in_package(package: str) -> set[str]:
    """Every module in a package (and any nested package), as dotted names.

    A package ``__init__`` is included: it is a module like any other, and a
    re-export in it would be a real escape hatch. Nested packages are expanded
    iteratively; recursing on the package's own ``__init__`` would re-glob the
    same directory forever.
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

    ``ast.walk`` rather than the module body alone, so a function-local import
    -- which is how v1 kept an optional dependency cheap -- is still found.
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
        f"{package} can reach the HTTP client via {sorted(offenders)}; Phase 2 is "
        "an offline phase and must never construct a request"
    )


def test_the_walk_actually_resolves_modules() -> None:
    """Guard the guard.

    A path helper that silently resolves nothing would make every test above
    pass vacuously, which is the failure mode this file exists to rule out.
    """
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
    """A dependency hidden inside a function body must still be found.

    This is how v1 kept optional imports cheap, and it is exactly the shape a
    module-level-only scanner misses.
    """
    reachable = reachable_modules({"edgar_sec.pipelines.filing_catalog.discovery"})
    assert "edgar_sec.infra.storage.duckdb" in reachable


def test_phase_one_pipeline_is_still_reachable_from_the_http_client() -> None:
    """The walk is sensitive enough to find a dependency that does exist.

    If this ever fails, the traversal stopped resolving real imports and every
    offline assertion above has quietly stopped meaning anything.
    """
    offenders = http_reachable("edgar_sec.pipelines.metadata_sync")
    assert offenders, (
        "Phase 1 fetches over HTTP; if it no longer does, this walk is broken"
    )
