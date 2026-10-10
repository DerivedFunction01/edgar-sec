"""Flag duplicated shared defaults and governed literals at identified call sites."""

from __future__ import annotations

import ast
from pathlib import Path

from .base import Scanner, ScannerFinding
from .files import discover_python_files

_OWNERS = {
    "DEFAULT_CHUNK_SIZE": "edgar_sec/foundation/runtime/settings/runtime.py",
    "DEFAULT_READ_BATCH_SIZE": "edgar_sec/foundation/runtime/settings/runtime.py",
    "DEFAULT_SQL_INSERT_BATCH_SIZE": "edgar_sec/foundation/runtime/settings/sql.py",
    "DEFAULT_ROW_GROUP_SIZE": "edgar_sec/foundation/runtime/settings/parquet.py",
    "DEFAULT_PARQUET_READ_BATCH_SIZE": "edgar_sec/foundation/runtime/settings/parquet.py",
    "DEFAULT_TARGET_BYTES": "edgar_sec/foundation/runtime/settings/catalog.py",
    "DEFAULT_IO_CHUNK_SIZE": "edgar_sec/foundation/io.py",
    "DEFAULT_WORKER_MEMORY_MIB": "edgar_sec/foundation/runtime/resources.py",
    "DEFAULT_WORKER_MEMORY_SAFETY": "edgar_sec/foundation/runtime/resources.py",
    "DEFAULT_MEMORY_FRACTION": "edgar_sec/foundation/runtime/resources.py",
}
_READ_BATCH_ARGUMENTS = frozenset({"batch_size", "batch_rows", "read_batch_size"})
_TARGET_BYTE_ARGUMENTS = frozenset({"target_bytes", "payload_target_bytes"})
_IO_CHUNK_ARGUMENTS = frozenset({"chunk_size", "read_size", "write_size"})
_IO_READ_ROLE = "io_read"
_ITERATION_BATCH_CALLS = frozenset({"fetchmany", "iter_batches", "to_arrow_reader"})
_BATCH_LITERAL_POLICIES = {
    "read batch": (4096, _READ_BATCH_ARGUMENTS),
    "Parquet read batch": (65536, frozenset({"batch_size", "batch_rows"})),
    "Parquet row group": (128000, frozenset({"row_group_size"})),
    "row-group size used as a read batch": (
        128000,
        frozenset({"batch_size", "batch_rows"}),
    ),
    "SQL insert batch": (1000, frozenset()),
    "document payload target": (
        96 * 1024 * 1024,
        _TARGET_BYTE_ARGUMENTS,
    ),
    "I/O chunk buffer": (65536, _IO_CHUNK_ARGUMENTS | {_IO_READ_ROLE}),
}
_LITERAL_EXEMPT_PATHS = frozenset(
    {
        "edgar_sec/foundation/runtime/settings/runtime.py",
        "edgar_sec/foundation/runtime/settings/sql.py",
        "edgar_sec/foundation/runtime/settings/parquet.py",
        "edgar_sec/foundation/io.py",
    }
)


def _integer(node: ast.AST) -> int | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
        left = _integer(node.left)
        right = _integer(node.right)
        if left is not None and right is not None:
            return left * right
    return None


def _assigned_names(node: ast.stmt) -> tuple[str, ...]:
    targets: list[ast.expr] = []
    if isinstance(node, ast.Assign):
        targets.extend(node.targets)
    elif isinstance(node, ast.AnnAssign):
        targets.append(node.target)
    names: list[str] = []
    for target in targets:
        if isinstance(target, ast.Name):
            names.append(target.id)
    return tuple(names)


def _literal_roles(node: ast.AST) -> tuple[tuple[str, int], ...]:
    roles: list[tuple[str, int]] = []
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        positional = [*node.args.posonlyargs, *node.args.args]
        defaults = [None] * (len(positional) - len(node.args.defaults)) + list(
            node.args.defaults
        )
        for argument, default in zip(positional, defaults, strict=True):
            if default is not None and argument.arg in (
                _READ_BATCH_ARGUMENTS | _TARGET_BYTE_ARGUMENTS | _IO_CHUNK_ARGUMENTS
            ):
                value = _integer(default)
                if value is not None:
                    roles.append((argument.arg, value))
        for argument, default in zip(node.args.kwonlyargs, node.args.kw_defaults):
            if default is not None and argument.arg in (
                _READ_BATCH_ARGUMENTS | _TARGET_BYTE_ARGUMENTS | _IO_CHUNK_ARGUMENTS
            ):
                value = _integer(default)
                if value is not None:
                    roles.append((argument.arg, value))
    if isinstance(node, ast.Call):
        function_name = (
            node.func.attr
            if isinstance(node.func, ast.Attribute)
            else node.func.id
            if isinstance(node.func, ast.Name)
            else None
        )
        for keyword in node.keywords:
            if keyword.arg is not None:
                value = _integer(keyword.value)
                if value is not None:
                    roles.append((keyword.arg, value))
        if function_name == "read" and node.args:
            value = _integer(node.args[0])
            if value is not None:
                roles.append((_IO_READ_ROLE, value))
        if function_name in _ITERATION_BATCH_CALLS and node.args:
            value = _integer(node.args[0])
            if value is not None:
                roles.append(("batch_size", value))
        if function_name == "range" and len(node.args) == 3:
            value = _integer(node.args[2])
            if value is not None:
                roles.append(("sql_insert_batch_size", value))
    return tuple(roles)


def scan_batch_defaults() -> list[ScannerFinding]:
    findings: list[ScannerFinding] = []
    for relative in discover_python_files():
        if not relative.startswith("edgar_sec/"):
            continue
        path = Path(relative)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.stmt, ast.Call)):
                continue
            if isinstance(node, ast.stmt):
                for name in _assigned_names(node):
                    owner = _OWNERS.get(name)
                    if owner is not None and relative != owner:
                        findings.append(
                            ScannerFinding(
                                scanner="batch-defaults",
                                source="static",
                                path=relative,
                                line=node.lineno,
                                message=f"{name} is owned by {owner}",
                                hint=f"import {name} from its owner instead of redefining it",
                            )
                        )
                    assigned_value = (
                        node.value
                        if isinstance(node, (ast.Assign, ast.AnnAssign))
                        else None
                    )
                    value = (
                        _integer(assigned_value) if assigned_value is not None else None
                    )
                    if (
                        owner is None
                        and "target_bytes" in name.lower()
                        and value == 96 * 1024 * 1024
                    ):
                        findings.append(
                            ScannerFinding(
                                scanner="batch-defaults",
                                source="static",
                                path=relative,
                                line=node.lineno,
                                message="literal 96 MiB duplicates the document payload target",
                                hint="use DEFAULT_TARGET_BYTES from settings/catalog.py",
                            )
                        )
            for role, value in _literal_roles(node):
                for label, (
                    governed_value,
                    arguments,
                ) in _BATCH_LITERAL_POLICIES.items():
                    if value != governed_value:
                        continue
                    if role not in arguments and not (
                        role == "sql_insert_batch_size" and label == "SQL insert batch"
                    ):
                        continue
                    if relative in _LITERAL_EXEMPT_PATHS:
                        continue
                    findings.append(
                        ScannerFinding(
                            scanner="batch-defaults",
                            source="static",
                            path=relative,
                            line=node.lineno,
                            message=f"literal {value} duplicates the shared {label} default",
                            hint="use the registered setting or its owner constant",
                        )
                    )
                    break
    return findings


SCANNER = Scanner(
    name="batch-defaults",
    description="flags duplicated shared defaults and governed literals at call sites",
    run=scan_batch_defaults,
)

__all__ = ["SCANNER", "scan_batch_defaults"]
