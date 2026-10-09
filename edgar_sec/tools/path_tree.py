"""Static path expression resolver and artifact-tree renderer."""

from __future__ import annotations

import ast
import importlib.util
import posixpath
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

NO_PATH_TREE = ":no-path-tree:"
NO_AUTOGEN_PATHS = "<!-- NO_AUTOGEN_PATHS -->"
NO_DOCGEN = ":no-docgen:"
IGNORE_PATH = ":ignore-path:"
IGNORE_COMMENT = "<!-- IGNORE -->"


@dataclass
class _Module:
    name: str
    path: Path
    tree: ast.Module
    imports: dict[str, tuple[str, str | None]] = field(default_factory=dict)
    definitions: dict[str, ast.AST] = field(default_factory=dict)
    constants: dict[str, ast.expr] = field(default_factory=dict)


@dataclass
class _Object:
    module: _Module
    node: ast.ClassDef
    fields: dict[str, Any]


@dataclass
class _ModuleRef:
    module: _Module


class _PathResolver:
    def __init__(self, source: Path) -> None:
        self.source = source.resolve()
        package_root = next(
            (parent for parent in self.source.parents if parent.name == "edgar_sec"),
            None,
        )
        if package_root is None:
            raise ValueError(f"path source is not under edgar_sec: {source}")
        self.repo_root = package_root.parent
        self.modules: dict[str, _Module] = {}
        self.active: set[tuple[str, str]] = set()
        self.module = self._load_path(self.source)

    def _load_path(self, path: Path, name: str | None = None) -> _Module:
        path = path.resolve()
        if name is None:
            relative = path.relative_to(self.repo_root).with_suffix("")
            parts = (
                relative.parts[:-1] if relative.name == "__init__" else relative.parts
            )
            name = ".".join(parts)
        cached = self.modules.get(name)
        if cached is not None:
            return cached
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        module = _Module(name, path, tree)
        self.modules[name] = module
        for item in tree.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                module.definitions[item.name] = item
            elif isinstance(item, ast.Assign):
                for target in item.targets:
                    if isinstance(target, ast.Name):
                        module.constants[target.id] = item.value
            elif isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                if item.value is not None:
                    module.constants[item.target.id] = item.value
            elif isinstance(item, ast.Import):
                for alias in item.names:
                    bound = alias.asname or alias.name.split(".")[0]
                    module.imports[bound] = (alias.name, None)
            elif isinstance(item, ast.ImportFrom):
                package = name.rpartition(".")[0]
                absolute = importlib.util.resolve_name(
                    f"{'.' * item.level}{item.module or ''}", package
                )
                for alias in item.names:
                    if alias.name != "*":
                        module.imports[alias.asname or alias.name] = (
                            absolute,
                            alias.name,
                        )
        return module

    def _external_module(self, name: str) -> _Module | None:
        if not name.startswith("edgar_sec.") and name != "edgar_sec":
            return None
        relative = Path(*name.split("."))
        source = self.repo_root / relative.with_suffix(".py")
        if not source.exists():
            source = self.repo_root / relative / "__init__.py"
        if not source.exists():
            return None
        return self._load_path(source, name)

    def _symbol(self, module: _Module, name: str) -> tuple[_Module, ast.AST] | None:
        definition = module.definitions.get(name)
        if definition is not None:
            return module, definition
        imported = module.imports.get(name)
        if imported is None:
            return None
        imported_module, imported_name = imported
        target = self._external_module(imported_module)
        if target is None:
            return None
        if imported_name is None:
            return target, target.tree
        definition = target.definitions.get(imported_name)
        if definition is not None:
            return target, definition
        expression = target.constants.get(imported_name)
        if expression is not None:
            return target, expression
        nested = target.imports.get(imported_name)
        if nested is not None:
            return self._symbol(target, imported_name)
        return None

    @staticmethod
    def _placeholder(name: str) -> str:
        return "{" + name + "}"

    @staticmethod
    def _is_path_annotation(annotation: ast.expr | None) -> bool:
        if annotation is None:
            return False
        if isinstance(annotation, ast.Name):
            return annotation.id == "Path"
        if isinstance(annotation, ast.Attribute):
            return annotation.attr == "Path"
        if isinstance(annotation, ast.BinOp) and isinstance(annotation.op, ast.BitOr):
            return _PathResolver._is_path_annotation(
                annotation.left
            ) or _PathResolver._is_path_annotation(annotation.right)
        if isinstance(annotation, ast.Subscript):
            return _PathResolver._is_path_annotation(annotation.value)
        return False

    @staticmethod
    def _sentinel(text: str | None) -> bool:
        return bool(
            text
            and any(
                marker in text for marker in (NO_DOCGEN, IGNORE_PATH, IGNORE_COMMENT)
            )
        )

    def render(self) -> str:
        module_doc = ast.get_docstring(self.module.tree) or ""
        if NO_PATH_TREE in module_doc or NO_AUTOGEN_PATHS in module_doc:
            return "No published artifact paths."
        entries: list[tuple[str, str, bool]] = []
        unresolved: list[str] = []
        for item in self.module.tree.body:
            if not isinstance(item, ast.ClassDef) or not item.name.endswith("Paths"):
                continue
            if any(
                isinstance(base, ast.Name) and base.id == "Protocol"
                for base in item.bases
            ):
                continue
            reference = self._abstract_object(self.module, item, {})
            for member in item.body:
                if not isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if member.name.startswith("_") or not self._is_path_annotation(
                    member.returns
                ):
                    continue
                doc = ast.get_docstring(member) or ""
                if self._sentinel(doc):
                    continue
                method_params = [
                    *member.args.posonlyargs,
                    *member.args.args,
                    *member.args.kwonlyargs,
                ]
                env = {
                    param.arg: self._placeholder(param.arg) for param in method_params
                }
                env["self"] = reference
                value = self._function_value(self.module, member, env)
                if not isinstance(value, str) or not value:
                    unresolved.append(f"{item.name}.{member.name}")
                    continue
                path = posixpath.normpath(value).strip("/")
                if path and path != ".":
                    is_directory = member.name.endswith(
                        ("_root", "_dir", "_directory", "_bundle")
                    ) or member.name in {"root", "directory"}
                    entries.append(
                        (
                            path,
                            doc.strip().splitlines()[0] if doc else "",
                            is_directory,
                        )
                    )
        if unresolved:
            names = ", ".join(unresolved)
            raise ValueError(
                f"unresolved Path methods in {self.module.path}: {names}; "
                "use a method sentinel for intentional exclusions"
            )
        return render_path_tree(entries)

    def _abstract_object(
        self, module: _Module, node: ast.ClassDef, fields: dict[str, Any]
    ) -> _Object:
        result = _Object(module, node, fields)
        for member in node.body:
            if not isinstance(member, ast.AnnAssign) or not isinstance(
                member.target, ast.Name
            ):
                continue
            name = member.target.id
            if name in result.fields:
                continue
            result.fields[name] = self._field_value(module, member.annotation, name)
        slots = next(
            (
                item.value
                for item in node.body
                if isinstance(item, ast.Assign)
                and any(
                    isinstance(target, ast.Name) and target.id == "__slots__"
                    for target in item.targets
                )
            ),
            None,
        )
        if isinstance(slots, (ast.Tuple, ast.List)):
            for item in slots.elts:
                if isinstance(item, ast.Constant) and isinstance(item.value, str):
                    result.fields.setdefault(item.value, self._placeholder(item.value))
        initializer = next(
            (
                item
                for item in node.body
                if isinstance(item, ast.FunctionDef) and item.name == "__init__"
            ),
            None,
        )
        if initializer is not None:
            for parameter in initializer.args.args[1:]:
                result.fields.setdefault(
                    parameter.arg, self._placeholder(parameter.arg)
                )
            init_env = {
                parameter.arg: result.fields[parameter.arg]
                for parameter in initializer.args.args[1:]
            }
            init_env["self"] = result
            for statement in initializer.body:
                if not isinstance(statement, (ast.Assign, ast.AnnAssign)):
                    continue
                value_node = statement.value
                if value_node is None:
                    continue
                value = self._expr(module, value_node, init_env, result)
                targets = (
                    statement.targets
                    if isinstance(statement, ast.Assign)
                    else [statement.target]
                )
                for target in targets:
                    if (
                        isinstance(target, ast.Attribute)
                        and isinstance(target.value, ast.Name)
                        and target.value.id == "self"
                        and value is not None
                    ):
                        result.fields[target.attr] = value
        return result

    def _field_value(self, module: _Module, annotation: ast.expr, name: str) -> Any:
        if self._is_path_annotation(annotation):
            return self._placeholder(name)
        type_name = annotation.id if isinstance(annotation, ast.Name) else None
        if type_name:
            symbol = self._symbol(module, type_name)
            if symbol and isinstance(symbol[1], ast.ClassDef):
                return self._abstract_object(symbol[0], symbol[1], {})
        return self._placeholder(name)

    def _module_attribute(self, module: _Module, name: str) -> Any:
        symbol = self._symbol(module, name)
        if symbol is None and name in module.constants:
            key = (module.name, name)
            if key in self.active:
                return None
            self.active.add(key)
            try:
                return self._expr(module, module.constants[name], {}, None)
            finally:
                self.active.remove(key)
        if symbol is None:
            return None
        owner, node = symbol
        if node is owner.tree:
            return _ModuleRef(owner)
        if isinstance(node, ast.expr):
            return self._expr(owner, node, {}, None)
        return (owner, node)

    def _expr(
        self,
        module: _Module,
        node: ast.expr,
        env: dict[str, Any],
        current: _Object | None,
    ) -> Any:
        if isinstance(node, ast.Constant):
            return node.value if isinstance(node.value, (str, int, float)) else None
        if isinstance(node, ast.Name):
            if node.id in env:
                return env[node.id]
            if current is not None and node.id == "self":
                return current
            if node.id == "Path":
                return "__Path__"
            if node.id in module.constants:
                key = (module.name, node.id)
                if key in self.active:
                    return None
                self.active.add(key)
                try:
                    return self._expr(module, module.constants[node.id], env, current)
                finally:
                    self.active.remove(key)
            imported = module.imports.get(node.id)
            if imported:
                target = self._external_module(imported[0])
                if target is not None:
                    if imported[1] is None:
                        return _ModuleRef(target)
                    return self._module_attribute(target, imported[1])
            symbol = self._symbol(module, node.id)
            if symbol:
                return symbol
            return None
        if isinstance(node, ast.Attribute):
            base = self._expr(module, node.value, env, current)
            if isinstance(base, _ModuleRef):
                return self._module_attribute(base.module, node.attr)
            if isinstance(base, _Object):
                if node.attr in base.fields:
                    return base.fields[node.attr]
                method = next(
                    (
                        part
                        for part in base.node.body
                        if isinstance(part, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and part.name == node.attr
                    ),
                    None,
                )
                if method is not None:
                    return self._function_value(base.module, method, {"self": base})
            return None
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            left = self._expr(module, node.left, env, current)
            right = self._expr(module, node.right, env, current)
            if isinstance(left, str) and isinstance(right, (str, int, float)):
                return posixpath.join(left, str(right))
            return None
        if isinstance(node, ast.JoinedStr):
            chunks: list[str] = []
            for value in node.values:
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    chunks.append(value.value)
                elif isinstance(value, ast.FormattedValue):
                    part = self._expr(module, value.value, env, current)
                    if isinstance(part, (str, int, float)):
                        chunks.append(str(part))
                    else:
                        return None
            return "".join(chunks)
        if isinstance(node, ast.Call):
            return self._call(module, node, env, current)
        if isinstance(node, ast.Subscript):
            return None
        if isinstance(node, ast.UnaryOp):
            return self._expr(module, node.operand, env, current)
        return None

    def _call(
        self,
        module: _Module,
        node: ast.Call,
        env: dict[str, Any],
        current: _Object | None,
    ) -> Any:
        if isinstance(node.func, ast.Attribute):
            receiver = self._expr(module, node.func.value, env, current)
            args = [self._expr(module, arg, env, current) for arg in node.args]
            if isinstance(receiver, _ModuleRef):
                target = self._module_attribute(receiver.module, node.func.attr)
                if isinstance(target, tuple) and isinstance(
                    target[1], (ast.FunctionDef, ast.AsyncFunctionDef)
                ):
                    return self._invoke(
                        target[0], target[1], None, node, env, current, module
                    )
            if node.func.attr == "resolve" and isinstance(receiver, str):
                return receiver
            if (
                node.func.attr == "replace"
                and isinstance(receiver, str)
                and len(args) == 2
            ):
                old, new = args
                if receiver.startswith("{") and receiver.endswith("}"):
                    return receiver
                if isinstance(old, str) and isinstance(new, str):
                    return receiver.replace(old, new)
            if isinstance(receiver, _Object):
                method = next(
                    (
                        item
                        for item in receiver.node.body
                        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and item.name == node.func.attr
                    ),
                    None,
                )
                if method is not None:
                    return self._invoke(
                        receiver.module, method, receiver, node, env, current, module
                    )
            return None
        if isinstance(node.func, ast.Name) and node.func.id == "Path":
            return self._expr(module, node.args[0], env, current) if node.args else None
        target = self._expr(module, node.func, env, current)
        if not isinstance(target, tuple):
            return None
        owner, definition = target
        if isinstance(definition, ast.ClassDef):
            return self._construct(owner, definition, node, env, current)
        if isinstance(definition, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return self._invoke(owner, definition, None, node, env, current, module)
        return None

    def _construct(
        self,
        module: _Module,
        node: ast.ClassDef,
        call: ast.Call,
        env: dict[str, Any],
        current: _Object | None,
    ) -> _Object:
        annotations = [
            item
            for item in node.body
            if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name)
        ]
        fields = {
            item.target.id: self._placeholder(item.target.id) for item in annotations
        }
        for item, argument in zip(annotations, call.args):
            fields[item.target.id] = self._expr(module, argument, env, current)
        for keyword in call.keywords:
            if keyword.arg is not None:
                fields[keyword.arg] = self._expr(module, keyword.value, env, current)
        return self._abstract_object(module, node, fields)

    def _invoke(
        self,
        module: _Module,
        function: ast.FunctionDef | ast.AsyncFunctionDef,
        receiver: _Object | None,
        call: ast.Call,
        caller_env: dict[str, Any],
        caller: _Object | None,
        caller_module: _Module | None = None,
    ) -> Any:
        scope = caller_module or module
        args = [self._expr(scope, arg, caller_env, caller) for arg in call.args]
        keywords = {
            item.arg: self._expr(scope, item.value, caller_env, caller)
            for item in call.keywords
            if item.arg is not None
        }
        params = [*function.args.posonlyargs, *function.args.args]
        if receiver is not None and params and params[0].arg == "self":
            params = params[1:]
        fn_env = {param.arg: self._placeholder(param.arg) for param in params}
        for param, value in zip(params, args):
            fn_env[param.arg] = value
        fn_env.update(keywords)
        if receiver is not None:
            fn_env["self"] = receiver
        return self._function_value(module, function, fn_env)

    def _function_value(
        self,
        module: _Module,
        function: ast.FunctionDef | ast.AsyncFunctionDef,
        env: dict[str, Any],
    ) -> Any:
        key = (module.name, f"{function.name}:{id(function)}")
        if key in self.active:
            return None
        self.active.add(key)
        try:
            local = dict(env)
            for statement in function.body:
                if isinstance(statement, ast.Expr) and isinstance(
                    statement.value, ast.Constant
                ):
                    continue
                if isinstance(statement, (ast.Assign, ast.AnnAssign)):
                    value_node = (
                        statement.value
                        if isinstance(statement, ast.Assign)
                        else statement.value
                    )
                    if value_node is None:
                        continue
                    value = self._expr(module, value_node, local, local.get("self"))
                    targets = (
                        statement.targets
                        if isinstance(statement, ast.Assign)
                        else [statement.target]
                    )
                    for target in targets:
                        if isinstance(target, ast.Name):
                            local[target.id] = (
                                value
                                if value is not None
                                else self._placeholder(target.id)
                            )
                    continue
                if isinstance(statement, ast.Return):
                    return (
                        self._expr(module, statement.value, local, local.get("self"))
                        if statement.value
                        else None
                    )
            return None
        finally:
            self.active.remove(key)


@dataclass
class _TreeNode:
    children: dict[str, _TreeNode] = field(default_factory=dict)
    description: str = ""
    terminal: bool = False
    directory: bool = False


def render_path_tree(
    entries: list[tuple[str, str] | tuple[str, str, bool]],
) -> str:
    roots: dict[str, _TreeNode] = {}
    for entry in entries:
        raw_path, description = entry[:2]
        explicit_directory = entry[2] if len(entry) == 3 else raw_path.endswith("/")
        parts = tuple(part for part in raw_path.split("/") if part)
        if len(parts) < 2:
            continue
        root = parts[0]
        node = roots.setdefault(root, _TreeNode(directory=True))
        for part in parts[1:]:
            node = node.children.setdefault(part, _TreeNode())
        node.terminal = True
        node.directory = explicit_directory or (
            len(entry) == 2 and "." not in parts[-1] and not parts[-1].startswith("*")
        )
        node.description = node.description or description
    if not roots:
        return "No published artifact paths."

    lines: list[str] = []
    ordered_roots = sorted(roots)
    for root_index, root in enumerate(ordered_roots):
        if root_index:
            lines.append("")
        lines.append(f"{root}/")
        _render_node_children(roots[root].children, "", lines)
    return "```text\n" + "\n".join(lines) + "\n```"


def _render_node_children(
    children: dict[str, _TreeNode], prefix: str, lines: list[str]
) -> None:
    names = sorted(
        children,
        key=lambda name: (
            not (children[name].directory or bool(children[name].children)),
            name,
        ),
    )
    for index, name in enumerate(names):
        node = children[name]
        last = index == len(names) - 1
        connector = "└── " if last else "├── "
        is_dir = node.directory or bool(node.children)
        label = name + ("/" if is_dir else "")
        comment = (
            f"  # {node.description}" if node.terminal and node.description else ""
        )
        lines.append(f"{prefix}{connector}{label}{comment}")
        if node.children:
            _render_node_children(
                node.children, prefix + ("    " if last else "│   "), lines
            )


def render_paths_tree(paths_file: Path) -> str:
    return _PathResolver(paths_file).render()
