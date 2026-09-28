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
            imported_mod: str | None = None
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported_mod = alias.name
                    _check_import(
                        findings,
                        path_str,
                        node.lineno,
                        caller_layer,
                        caller_rank,
                        imported_mod,
                    )
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_mod = node.module
                _check_import(
                    findings,
                    path_str,
                    node.lineno,
                    caller_layer,
                    caller_rank,
                    imported_mod,
                )

    return findings


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
