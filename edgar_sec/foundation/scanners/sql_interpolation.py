"""Policy scanner banning SQL built from unescaped values at a SQL sink.

A statement assembled with an f-string treats every interpolated value as
trusted. That is safe only for a value that went through an escaping helper on
its way in. A filesystem path, a manifest field, or anything a caller supplied
is not trusted, and a single quote in one of those either breaks the statement or
ends it early.

This repository had five independent escaping helpers and nothing that checked
any of them, so a module could concatenate a raw path into a statement and pass
the gate. The defect this scanner exists to prevent is concrete: document
snapshot assembly interpolated its chunk paths with no escaping at all, and no
test covered a quoted path because no rule required one.

The rule is deliberately narrow, in the ``artifact-paths`` idiom:

* it inspects the **argument of a SQL sink**, so composing a statement into a
  local and passing that local is unaffected — which is the spelling this
  codebase already uses for every large query;
* a value is accepted when it reached the f-string through an **escaping
  helper**, through a constant, or through a local bound to one of those, so a
  correctly escaped statement is not reported;
* anything else interpolated at the sink is a finding, which is what makes a new
  query site a decision rather than an accident;
* tests are exempt, because a test that exercises a query builder must hand that
  builder's output to a connection.

A bound parameter (``con.execute(sql, [value])``) is never a finding: that is the
safe path this rule steers code toward.
"""

from __future__ import annotations

import ast
from pathlib import Path

from .base import Scanner, ScannerFinding
from .files import discover_python_files

#: Methods that hand a string to the database as a statement. ``cursor.execute``
#: and duckdb's ``con.execute`` share the name, which is the point: the rule is
#: about the argument, not about which driver received it.
_SQL_SINKS = frozenset({"execute", "executemany", "executescript"})

#: Helpers whose return value is already a safe SQL fragment. Matching on the
#: final name component lets a caller reach them through any import path.
_ESCAPING_HELPERS = frozenset(
    {
        "sql_identifier",
        "sql_literal",
        "sql_path_list",
        "date_projection_sql",
        "date_selection_sql",
        "parsed_date_relation",
        "suffix_sql",
    }
)

#: Calls whose result is a plain number or a join of already-safe text. A
#: ``", ".join(...)`` over escaped literals is as safe as the literals it joins,
#: so a pipeline may assemble a list without losing its escaping.
_NEUTRAL_CALLS = frozenset({"join", "int", "float", "bool", "len", "str", "sorted"})

#: Modules declared to compose SQL at a query sink, each audited individually.
#: An entry is a claim that every value reaching the statement there is either a
#: literal the module owns or one routed through an escaping helper:
#:
#: * ``duckdb.py`` — the dialect owner. It *defines* the escaping helpers, so it
#:   has to assemble the COPY envelope itself; its ``query`` argument is a
#:   composed statement by contract and ``compression`` is a format keyword.
#: * ``source.py`` — temp-table names come from a closed constant set, and every
#:   interpolated column is checked against ``KNOWN_DIMENSIONS`` first.
#: * ``inventory.py`` — dimension names are checked against the policy
#:   vocabulary, and its relation is built through ``sql_literal``.
#: * ``planner.py`` — composes predicate fragments from the escaping helpers and
#:   names the temp views it creates two lines earlier.
#: * ``fixture_store.py`` — a SQLite adapter that interpolates only its own
#:   table-name and column-name constants.
#:
#: The rule's strength is at the boundary: a module that composes SQL and is not
#: on this list is reported. It does not police the interior of a declared
#: module, which is why each entry is an audited claim rather than a blanket
#: exemption.
_SQL_COMPILER_PATHS = frozenset(
    {
        "edgar_sec/infra/storage/duckdb.py",
        "edgar_sec/engine/selection/source.py",
        "edgar_sec/engine/selection/inventory.py",
        "edgar_sec/pipelines/filing_catalog/planner.py",
        "edgar_sec/pipelines/document_storage/fixture_store.py",
    }
)

#: The reader surface composes statements from a schema DuckDB itself reported
#: rather than from caller input, and the operator guard is a scanner, not a
#: statement. Neither is a place where this rule applies.
_EXEMPT_PREFIXES = (
    "edgar_sec/apps/viewer/",
    "edgar_sec/foundation/sql/",
    "edgar_sec/foundation/scanners/sql_interpolation.py",
)


def _is_test_path(normalized: str) -> bool:
    """Return whether ``normalized`` names a test module.

    Matched on path *components* rather than a substring, because a substring
    test also matches a directory that merely starts with ``test_`` — which is
    every pytest ``tmp_path``, and would exempt a synthetic module the scanner is
    meant to judge.
    """
    parts = normalized.split("/")
    if not parts:
        return False
    if parts[0] == "tests":
        return True
    if "tests" in parts[:-1]:
        return True
    name = parts[-1]
    return name.startswith("test_") or name.endswith("_test.py")


def _is_exempt(path_str: str) -> bool:
    normalized = path_str.replace("\\", "/")
    return (
        normalized in _SQL_COMPILER_PATHS
        or normalized.startswith(_EXEMPT_PREFIXES)
        or _is_test_path(normalized)
    )


def _called_name(node: ast.Call) -> str:
    function = node.func
    if isinstance(function, ast.Name):
        return function.id
    if isinstance(function, ast.Attribute):
        return function.attr
    return ""


def _escaped_locals(tree: ast.AST) -> set[str]:
    """Return local names whose value is already safe SQL text.

    Only a direct binding counts: ``query = f"...{sql_literal(p)}..."`` makes
    ``query`` safe, so passing ``query`` to a sink is fine. Rebinding it to
    something unescaped does not launder the name, because the walk keeps the
    last binding it sees rather than the first.
    """
    safe: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and _is_safe_text(node.value, safe):
                safe.add(target.id)
            elif isinstance(target, ast.Name):
                safe.discard(target.id)
    return safe


def _comprehension_is_safe(node: ast.expr, safe_names: set[str]) -> bool:
    """Return whether the value a comprehension produces is safe text."""
    if isinstance(node, (ast.GeneratorExp, ast.ListComp, ast.SetComp)):
        return _is_safe_text(node.elt, safe_names)
    if isinstance(node, ast.DictComp):
        return _is_safe_text(node.key, safe_names) and _is_safe_text(
            node.value, safe_names
        )
    return False


def _is_safe_text(node: ast.expr, safe_names: set[str]) -> bool:
    """Return whether ``node`` is SQL text that needs no further escaping."""
    if isinstance(node, ast.Constant):
        return isinstance(node.value, str)
    if isinstance(node, ast.Name):
        return node.id in safe_names
    if isinstance(node, ast.JoinedStr):
        return all(
            _is_safe_text(value.value, safe_names)
            for value in node.values
            if isinstance(value, ast.FormattedValue)
        )
    if _comprehension_is_safe(node, safe_names):
        return True
    if isinstance(node, ast.Call):
        name = _called_name(node)
        if name in _ESCAPING_HELPERS:
            return True
        if name in _NEUTRAL_CALLS:
            return all(_is_safe_text(argument, safe_names) for argument in node.args)
    return False


def _first_positional(call: ast.Call) -> ast.expr | None:
    return call.args[0] if call.args else None


def _statement_findings(node: ast.expr, safe_names: set[str]) -> list[ast.expr]:
    """Return the interpolated values in ``node`` that are not escaped."""
    if isinstance(node, ast.JoinedStr):
        return [
            value.value
            for value in node.values
            if isinstance(value, ast.FormattedValue)
            and not _is_safe_text(value.value, safe_names)
        ]
    if isinstance(node, ast.BinOp):
        unescaped: list[ast.expr] = []
        for side in (node.left, node.right):
            if isinstance(side, ast.Constant) and isinstance(side.value, str):
                continue
            if not _is_safe_text(side, safe_names):
                unescaped.append(side)
        return unescaped
    return []


def scan_sql_interpolation() -> list[ScannerFinding]:
    """Scan for SQL built from unescaped values at a SQL sink."""
    findings: list[ScannerFinding] = []

    for path_str in discover_python_files():
        if _is_exempt(path_str):
            continue

        path = Path(path_str)
        if not path.is_file():
            continue

        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=path_str)
        except (SyntaxError, UnicodeDecodeError):
            continue

        safe_names = _escaped_locals(tree)

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            function = node.func
            if not isinstance(function, ast.Attribute):
                continue
            if function.attr not in _SQL_SINKS:
                continue
            statement = _first_positional(node)
            if statement is None:
                continue
            unescaped = _statement_findings(statement, safe_names)
            if not unescaped:
                continue
            findings.append(
                ScannerFinding(
                    scanner="sql-interpolation",
                    source="static",
                    path=path_str,
                    line=node.lineno,
                    message=(
                        f"SQL passed to {function.attr}() interpolates "
                        f"{len(unescaped)} unescaped value(s)"
                    ),
                    hint=(
                        "bind the value as a parameter, or route it through "
                        "infra.storage.duckdb.sql_literal / sql_path_list so an "
                        "embedded quote cannot terminate the statement"
                    ),
                )
            )
    return findings


SCANNER = Scanner(
    name="sql-interpolation",
    description="flags SQL assembled from unescaped values at a query sink",
    run=scan_sql_interpolation,
)

__all__ = ["SCANNER", "scan_sql_interpolation"]
