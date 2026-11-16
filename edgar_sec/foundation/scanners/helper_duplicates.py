"""Scanner flagging duplicated helper bodies outside their scaffold homes.
Flags a non-method function whose docstring-stripped body duplicates a body
in another module or a home, and the parameterized-get shape outside the
homes. Allows methods, sub-six-node one-statement bodies, and the homes.
"""

from __future__ import annotations

import ast
from pathlib import Path

from .base import Scanner, ScannerFinding
from .files import discover_python_files
from .lines import is_scanner_infrastructure

_HOMES = (
    "edgar_sec/engine/forms/common/family_scaffold.py",
    "edgar_sec/engine/forms/common/row_extraction.py",
    "edgar_sec/engine/company_family/cohort.py",
    "edgar_sec/apps/client/operator_kit.py",
    "edgar_sec/infra/run_lock.py",
    "edgar_sec/infra/storage/dag/publication.py",
)

# Sanctioned divergences (coordinator rulings, 2026-11-15), transcribed
# from the census register: near-miss helper pairs whose bodies diverge
# in served semantics, so no collapse is a dedupe act. This scanner
# measures identical bodies and never fires on them; the entries make
# the sanctions visible at the owning scanner.
_SANCTIONED_DIVERGENCES = (
    ("edgar_sec/apps/client/financials_ttm.py", "_length_class"),
    ("edgar_sec/apps/client/operator_config.py", "_error_result"),
    ("edgar_sec/apps/client/operator.py", "_error_result"),
)

_MIN_NODES = 6

_HINT = (
    "home the helper in edgar_sec.engine.forms.common.family_scaffold or "
    "edgar_sec.apps.client.operator_kit and import it instead of keeping a "
    "private copy"
)

_FIELDS_OF_HINT = (
    "call fields_of(rep, form_key) from "
    "edgar_sec.engine.forms.common.family_scaffold instead of defining a "
    "private parameterized get"
)


def _body_statements(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.stmt]:
    body = list(node.body)
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]
    return body


def _body_key(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    body = _body_statements(node)
    if not body:
        return None
    module = ast.Module(body=body, type_ignores=[])
    node_count = sum(1 for _ in ast.walk(module))
    if len(body) < 2 and node_count < _MIN_NODES:
        return None
    return ast.dump(module)


def _is_fields_of_shape(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    body = _body_statements(node)
    if len(body) != 1 or not isinstance(body[0], ast.Return):
        return False
    call = body[0].value
    if not isinstance(call, ast.Call) or call.keywords:
        return False
    func = call.func
    if not isinstance(func, ast.Attribute) or func.attr != "get":
        return False
    if len(call.args) != 2:
        return False
    key, default = call.args
    return (
        isinstance(key, ast.Constant)
        and isinstance(key.value, str)
        and isinstance(default, ast.Dict)
        and not default.keys
    )


def _functions(tree: ast.Module) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    found: list[ast.FunctionDef | ast.AsyncFunctionDef] = []

    def visit(node: ast.AST, in_class: bool) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                visit(child, True)
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not in_class:
                    found.append(child)
                visit(child, in_class)
            else:
                visit(child, in_class)

    visit(tree, False)
    return found


def _parse(path: str) -> ast.Module | None:
    try:
        return ast.parse(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, SyntaxError):
        return None


def scan_helper_duplicates() -> list[ScannerFinding]:
    """Flag duplicated helper bodies and private parameterized gets."""
    home_keys: dict[str, str] = {}
    for home in _HOMES:
        tree = _parse(home)
        if tree is None:
            continue
        for node in _functions(tree):
            key = _body_key(node)
            if key is not None:
                home_keys.setdefault(key, home)

    collected: list[
        tuple[str, ast.FunctionDef | ast.AsyncFunctionDef, str | None]
    ] = []
    by_key: dict[str, list[str]] = {}
    for path in discover_python_files():
        if path in _HOMES or is_scanner_infrastructure(path):
            continue
        tree = _parse(path)
        if tree is None:
            continue
        for node in _functions(tree):
            key = _body_key(node)
            collected.append((path, node, key))
            if key is not None:
                by_key.setdefault(key, []).append(path)

    findings: list[ScannerFinding] = []
    for path, node, key in collected:
        if _is_fields_of_shape(node):
            findings.append(
                ScannerFinding(
                    scanner="helper-duplicates",
                    source="scan",
                    path=path,
                    line=node.lineno,
                    message=(
                        f"private parameterized get {node.name!r} "
                        "outside its home"
                    ),
                    hint=_FIELDS_OF_HINT,
                )
            )
            continue
        if key is None:
            continue
        if key in home_keys:
            findings.append(
                ScannerFinding(
                    scanner="helper-duplicates",
                    source="scan",
                    path=path,
                    line=node.lineno,
                    message=(
                        f"helper body {node.name!r} duplicates its home "
                        f"in {home_keys[key]}"
                    ),
                    hint=_HINT,
                )
            )
            continue
        others = {other for other in by_key.get(key, []) if other != path}
        if others:
            findings.append(
                ScannerFinding(
                    scanner="helper-duplicates",
                    source="scan",
                    path=path,
                    line=node.lineno,
                    message=(
                        f"helper body {node.name!r} is duplicated in "
                        f"{sorted(others)[0]}"
                    ),
                    hint=_HINT,
                )
            )
    return findings


SCANNER = Scanner(
    name="helper-duplicates",
    description=(
        "scan for function bodies duplicated across modules or against the "
        "scaffold and operator-kit homes, and for private parameterized-get "
        "helpers outside family_scaffold"
    ),
    run=scan_helper_duplicates,
)
