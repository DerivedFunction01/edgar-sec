"""AST Scanner enforcing acyclic downward-only layer dependencies."""

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
}


def scan_layer_boundary() -> list[ScannerFinding]:
    """Enforces downward-only layer dependencies in edgar_sec."""
    findings: list[ScannerFinding] = []

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
                    _check_import(
                        findings,
                        path_str,
                        node.lineno,
                        caller_layer,
                        caller_rank,
                        f"{module}.{alias.name}",
                    )

    return findings


def _resolve_relative(
    node: ast.ImportFrom, path_str: str, caller_layer: str
) -> str | None:
    """Resolve an ``ImportFrom`` to a dotted path, relative or absolute.

    ``from ..infra.storage import duckdb`` inside a Layer 0 module is exactly as
    much an upward import as the absolute spelling, and the absolute form was
    the only one this scanner caught. Relative imports carry no package prefix,
    so the target has to be reconstructed from the importing file's own depth:
    one leading dot means the current package, and each additional dot climbs
    one parent directory.
    """
    if node.level == 0:
        return node.module

    parts = path_str.split("/")
    # The last element is the file itself; everything before it is the package
    # path, and the first element is the ``edgar_sec`` prefix that
    # ``_check_import`` matches on. Climbing past the package root must never
    # happen, so the walk is bounded by the file's depth inside the package.
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
