"""Scanner requiring every constructed SEC URL shape to have a governed surface.

It reads the classification rule table statically from the domain URL module
and flags https SEC URL constants no rule classifies, plus any rule or builder
surface with no freshness-policy row. http-scheme strings are namespaces.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from edgar_sec.foundation.runtime.settings.sec import (
    SURFACE_KIND_NO_STORE,
    SURFACE_KIND_STATIC,
    SURFACE_KIND_TRANSIENT,
    SURFACE_POLICIES,
)

_KNOWN_SURFACE_KINDS = {
    SURFACE_KIND_STATIC,
    SURFACE_KIND_TRANSIENT,
    SURFACE_KIND_NO_STORE,
}
_SETTINGS_MODULE = "edgar_sec/foundation/runtime/settings/sec.py"

from .base import Scanner, ScannerFinding
from .files import discover_python_files

_URL_MODULE = "edgar_sec/domain/sec_urls.py"
_EXEMPT_PATHS = {
    # Owns the URL vocabulary; its rules and builders are cross-checked instead.
    _URL_MODULE,
    # SourceRef citations are provenance anchors, never fetched URLs.
    "edgar_sec/domain/forms/exhibits/coverage.py",
}


@dataclass
class _RuleBook:
    rules: list[tuple[str, str, re.Pattern[str], re.Pattern[str] | None]] = field(
        default_factory=list
    )
    surfaces: dict[str, int] = field(default_factory=dict)


def _constant_string(node: ast.AST, constants: dict[str, str]) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return constants.get(node.id)
    return None


def _load_rule_book() -> _RuleBook:
    """Extract the surface rule table and builder surfaces from the URL module."""
    book = _RuleBook()
    path = Path(_URL_MODULE)
    if not path.is_file():
        return book
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, SyntaxError):
        return book
    constants: dict[str, str] = {}
    for node in tree.body:
        target: ast.AST | None = None
        assigned: ast.expr | None = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, assigned = node.targets[0], node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            target, assigned = node.target, node.value
        if not isinstance(target, ast.Name) or assigned is None:
            continue
        name = target.id
        if name.startswith("SURFACE_"):
            value = _constant_string(assigned, constants)
            if value is not None:
                constants[name] = value
        elif name == "SEC_SURFACE_RULES" and isinstance(assigned, ast.Tuple):
            for element in assigned.elts:
                if not (isinstance(element, ast.Tuple) and len(element.elts) in (3, 4)):
                    continue
                surface = _constant_string(element.elts[0], constants)
                host = _constant_string(element.elts[1], constants)
                pattern = _constant_string(element.elts[2], constants)
                if surface is None or host is None or pattern is None:
                    continue
                query: str | None = None
                if len(element.elts) == 4:
                    query_node = element.elts[3]
                    if not (
                        isinstance(query_node, ast.Constant)
                        and query_node.value is None
                    ):
                        query = _constant_string(query_node, constants)
                        if query is None:
                            continue
                book.rules.append(
                    (
                        surface,
                        host,
                        re.compile(pattern),
                        re.compile(query) if query else None,
                    )
                )
                book.surfaces.setdefault(surface, element.lineno)
        elif name == "URL_BUILDER_SURFACES" and isinstance(assigned, ast.Dict):
            for value_node in assigned.values:
                surface = _constant_string(value_node, constants)
                if surface is not None:
                    book.surfaces.setdefault(surface, value_node.lineno)
    return book


def _classify(book: _RuleBook, url: str) -> str | None:
    parts = urlsplit(url)
    host = (parts.hostname or "").casefold()
    path = parts.path or ""
    query = parts.query or ""
    for surface, rule_host, pattern, query_pattern in book.rules:
        if host != rule_host or not pattern.search(path):
            continue
        if query_pattern is not None and not query_pattern.search(query):
            continue
        return surface
    return None


def _is_exempt(path_str: str) -> bool:
    normalized = path_str.replace("\\", "/")
    return (
        normalized in _EXEMPT_PATHS
        or normalized.startswith("tests/")
        or "/tests/" in normalized
        or "edgar_sec/foundation/scanners/" in normalized
    )


def _url_constants(tree: ast.AST) -> list[ast.Constant]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value.startswith("https://")
        and "sec.gov" in node.value
    ]


def scan_sec_surfaces() -> list[ScannerFinding]:
    """Scan Python files for SEC URL shapes with no governed surface."""
    findings: list[ScannerFinding] = []
    book = _load_rule_book()
    for surface, policy in sorted(SURFACE_POLICIES.items()):
        if policy.kind not in _KNOWN_SURFACE_KINDS:
            findings.append(
                ScannerFinding(
                    scanner="sec-surface",
                    source="static",
                    path=_SETTINGS_MODULE,
                    line=1,
                    message=f"SEC surface {surface!r} has unknown kind {policy.kind!r}",
                    hint="use a governed surface kind in SURFACE_POLICIES",
                )
            )
        elif policy.kind == SURFACE_KIND_NO_STORE and policy.ttl_path is not None:
            findings.append(
                ScannerFinding(
                    scanner="sec-surface",
                    source="static",
                    path=_SETTINGS_MODULE,
                    line=1,
                    message=f"no-store SEC surface {surface!r} must not name a TTL",
                    hint="a no-store surface is never cached, so it carries no TTL",
                )
            )
    for surface, line in sorted(book.surfaces.items()):
        if surface not in SURFACE_POLICIES:
            findings.append(
                ScannerFinding(
                    scanner="sec-surface",
                    source="static",
                    path=_URL_MODULE,
                    line=line,
                    message=f"SEC surface {surface!r} has no freshness-policy row",
                    hint=(
                        "register the surface in SURFACE_POLICIES in the SEC "
                        "settings provider"
                    ),
                )
            )
    for path_str in discover_python_files():
        if _is_exempt(path_str):
            continue
        path = Path(path_str)
        if not path.is_file():
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        for node in _url_constants(tree):
            if _classify(book, node.value) is None:
                findings.append(
                    ScannerFinding(
                        scanner="sec-surface",
                        source="static",
                        path=path_str,
                        line=node.lineno,
                        message=(
                            f"SEC URL shape has no governed surface: {node.value!r}"
                        ),
                        hint=(
                            "classify the shape in edgar_sec.domain.sec_urls "
                            "and register its freshness policy in the SEC "
                            "settings provider"
                        ),
                    )
                )
    return findings


SCANNER = Scanner(
    name="sec-surface",
    description="flags SEC URL shapes constructed without a governed surface",
    run=scan_sec_surfaces,
)

__all__ = ["SCANNER", "scan_sec_surfaces"]
