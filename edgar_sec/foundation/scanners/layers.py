"""AST scanner enforcing layer boundaries and bounded pipeline imports.

Cross-pipeline imports are limited to matching ``paths.py`` or ``schemas.py`` modules.
"""

from __future__ import annotations

import ast
from pathlib import Path

from .base import Scanner, ScannerFinding
from .files import discover_python_files

_LAYER_RANK = {
    "foundation": 0,
    "domain": 1,
    "infra": 2,
    "engine": 3,
    "pipelines": 4,
    "apps": 5,
    "tools": 6,
}


def scan_layer_boundary() -> list[ScannerFinding]:
    """Enforce layer dependencies and isolated cross-pipeline path/schema imports."""
    findings: list[ScannerFinding] = []
    pipeline_edges: dict[str, list[tuple[str, str, int]]] = {
        "paths": [],
        "schemas": [],
    }

    for path_str in discover_python_files():
        if not path_str.startswith("edgar_sec/"):
            continue
        parts = path_str.split("/")
        if len(parts) < 3:
            continue
        caller_layer = parts[1]
        if caller_layer not in _LAYER_RANK:
            continue
        caller_rank = _LAYER_RANK[caller_layer]

        path = Path(path_str)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=path_str)
        except (SyntaxError, UnicodeDecodeError):
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    edge_kind = _check_cross_pipeline_import(
                        findings,
                        path_str,
                        node.lineno,
                        alias.name,
                        alias.asname,
                        None,
                    )
                    if edge_kind is not None:
                        pipeline_edges[edge_kind].append(
                            (parts[2], alias.name.split(".")[2], node.lineno)
                        )
                    _check_import(
                        findings,
                        path_str,
                        node.lineno,
                        caller_layer,
                        caller_rank,
                        alias.name,
                    )
            elif isinstance(node, ast.ImportFrom):
                module = _resolve_relative(node, path_str, caller_layer)
                if module is None:
                    continue
                for alias in node.names:
                    edge_kind = _check_cross_pipeline_import(
                        findings,
                        path_str,
                        node.lineno,
                        module,
                        alias.asname,
                        alias.name,
                    )
                    if edge_kind is not None:
                        pipeline_edges[edge_kind].append(
                            (parts[2], module.split(".")[2], node.lineno)
                        )
                    _check_import(
                        findings,
                        path_str,
                        node.lineno,
                        caller_layer,
                        caller_rank,
                        f"{module}.{alias.name}",
                    )

    for kind, edges in pipeline_edges.items():
        findings.extend(_cross_pipeline_cycles(kind, edges))
    return findings


def _check_cross_pipeline_import(
    findings: list[ScannerFinding],
    path_str: str,
    lineno: int,
    imported_module: str,
    asname: str | None,
    imported_name: str | None,
) -> str | None:
    caller_parts = path_str.split("/")
    target_parts = imported_module.split(".")
    if (
        len(caller_parts) < 4
        or caller_parts[1] != "pipelines"
        or len(target_parts) < 3
        or target_parts[:2] != ["edgar_sec", "pipelines"]
        or caller_parts[2] == target_parts[2]
    ):
        return None

    caller_kind = Path(path_str).stem
    target_kind = target_parts[-1]
    if caller_kind not in {"paths", "schemas"} and target_kind not in {
        "paths",
        "schemas",
    }:
        return None
    allowed = (
        caller_kind in {"paths", "schemas"}
        and target_kind == caller_kind
        and len(target_parts) == 4
        and asname is None
        and imported_name != "*"
    )
    if allowed:
        return caller_kind

    findings.append(
        ScannerFinding(
            scanner="layer-boundary",
            source="static",
            path=path_str,
            line=lineno,
            message=(
                f"Illegal cross-pipeline import from '{caller_parts[2]}' "
                f"to '{target_parts[2]}'"
            ),
            hint=(
                "Use a direct matching paths.py or schemas.py import only from the "
                "corresponding owner module."
            ),
        )
    )
    return None


def _cross_pipeline_cycles(
    kind: str, edges: list[tuple[str, str, int]]
) -> list[ScannerFinding]:
    adjacency: dict[str, list[tuple[str, int]]] = {}
    for source, target, line in edges:
        adjacency.setdefault(source, []).append((target, line))

    state: dict[str, int] = {}
    stack: list[str] = []
    findings: list[ScannerFinding] = []

    def visit(node: str) -> None:
        state[node] = 1
        stack.append(node)
        for target, line in adjacency.get(node, []):
            if state.get(target) == 1:
                start = stack.index(target)
                cycle = [*stack[start:], target]
                findings.append(
                    ScannerFinding(
                        scanner="layer-boundary",
                        source="static",
                        path=f"edgar_sec/pipelines/{node}/{kind}.py",
                        line=line,
                        message=(
                            f"Cross-pipeline {kind}.py import cycle: "
                            f"{' -> '.join(cycle)}"
                        ),
                        hint="Break the cycle by moving the shared contract lower.",
                    )
                )
            elif state.get(target, 0) == 0:
                visit(target)
        stack.pop()
        state[node] = 2

    for node in sorted(adjacency):
        if state.get(node, 0) == 0:
            visit(node)
    return findings


def _resolve_relative(
    node: ast.ImportFrom, path_str: str, caller_layer: str
) -> str | None:
    """Resolve an ``ImportFrom`` to a dotted path, relative or absolute.

    A relative import carries no package prefix, so the target is rebuilt from the
    importing file's own depth; the walk is bounded so it cannot climb past the root.
    """
    if node.level == 0:
        return node.module

    parts = path_str.split("/")
    # The last element is the file itself; the first is the ``edgar_sec`` prefix
    # ``_check_import`` matches on.
    package_parts = parts[:-1]
    climb = node.level - 1
    if climb > len(package_parts) - 1:
        return None
    base = package_parts[: len(package_parts) - climb] if climb else package_parts

    if node.module:
        return ".".join([*base, *node.module.split(".")])
    return ".".join(base)


def _check_import(
    findings: list[ScannerFinding],
    path_str: str,
    lineno: int,
    caller_layer: str,
    caller_rank: int,
    imported_mod: str,
) -> None:
    if not imported_mod.startswith("edgar_sec."):
        return
    mod_parts = imported_mod.split(".")
    if len(mod_parts) < 2:
        return
    callee_layer = mod_parts[1]
    if callee_layer not in _LAYER_RANK:
        return
    callee_rank = _LAYER_RANK[callee_layer]

    if callee_rank > caller_rank:
        findings.append(
            ScannerFinding(
                scanner="layer-boundary",
                source="static",
                path=path_str,
                line=lineno,
                message=(
                    f"Illegal upward import: '{caller_layer}' (layer {caller_rank}) "
                    f"cannot import from '{callee_layer}' (layer {callee_rank})"
                ),
                hint="Invert the dependency via SPI or move the abstraction to a lower layer.",
            )
        )


SCANNER = Scanner(
    name="layer-boundary",
    description="enforce acyclic downward-only imports in edgar_sec",
    run=scan_layer_boundary,
)
