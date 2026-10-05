"""AST-based static import lineage analyzer and targeted test resolver."""

from __future__ import annotations

import ast
import json
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path

from edgar_sec.foundation.runtime.paths import TRANSIENT_DIR, resolve_paths

CACHE_VERSION = 1


def default_cache_path(repo_root: Path) -> Path:
    paths = resolve_paths(repo_root)
    return paths.artifacts_root / TRANSIENT_DIR / "cache" / "dep_graph.json"


@dataclass(frozen=True)
class FileImportData:
    mtime_ns: int
    module: str
    imports: tuple[str, ...]


@dataclass(frozen=True)
class TestSelectionResult:
    test_files: tuple[str, ...]
    reasons: dict[str, list[str]] = field(default_factory=dict)
    is_full_suite: bool = False
    is_docs_only: bool = False

    @property
    def has_tests(self) -> bool:
        return bool(self.test_files)


def path_to_module(rel_path: str) -> str:
    """Convert relative python file path to canonical module dotted path."""
    p = Path(rel_path)
    parts = list(p.parts)
    if parts and parts[-1].endswith(".py"):
        parts[-1] = parts[-1][:-3]
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def resolve_relative_import(
    current_module: str, level: int, target_name: str | None
) -> str:
    """Canonicalize relative import (e.g. level=2 from ..common into dotted name)."""
    parts = current_module.split(".")
    # If current_module is edgar_sec.a.b, its package is edgar_sec.a; level 1 drops one
    # part, level 2 drops two.
    if level > len(parts):
        return target_name or ""
    base_parts = parts[: len(parts) - level]
    if target_name:
        return ".".join((*base_parts, target_name))
    return ".".join(base_parts)


def parse_file_imports(file_path: Path, rel_str: str) -> tuple[str, tuple[str, ...]]:
    """Parse a Python file with ast and extract internal edgar_sec / tests imports."""
    module_name = path_to_module(rel_str)
    try:
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(file_path))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return module_name, ()

    discovered: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.name
                if name.startswith(("edgar_sec.", "tests.")):
                    discovered.add(name)
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                resolved = resolve_relative_import(module_name, node.level, node.module)
                if resolved.startswith(("edgar_sec.", "tests.")):
                    discovered.add(resolved)
            elif node.module and node.module.startswith(("edgar_sec.", "tests.")):
                discovered.add(node.module)

    return module_name, tuple(sorted(discovered))


def find_mirror_test(source_path: str, repo_root: Path) -> str | None:
    """Map edgar_sec/<pkg>/<mod>.py to tests/<pkg>/test_<mod>.py if it exists."""
    p = Path(source_path)
    parts = list(p.parts)
    if not parts or parts[0] != "edgar_sec" or not parts[-1].endswith(".py"):
        return None
    if parts[-1] == "__init__.py":
        return None

    filename = parts[-1]
    test_filename = f"test_{filename}"
    candidate_parts = ["tests", *parts[1:-1], test_filename]
    candidate = Path(*candidate_parts)
    if (repo_root / candidate).is_file():
        return str(candidate)
    return None


class LineageGraph:
    """Manages the static dependency graph between modules and tests with mtime caching."""

    def __init__(self, repo_root: Path, cache_path: Path | None = None):
        self.repo_root = repo_root
        self.cache_path = (
            cache_path if cache_path is not None else default_cache_path(repo_root)
        )
        self._entries: dict[str, FileImportData] = {}

    def load_cache(self) -> None:
        if not self.cache_path.is_file():
            return
        try:
            raw = json.loads(self.cache_path.read_text(encoding="utf-8"))
            if raw.get("version") != CACHE_VERSION:
                return
            files_dict = raw.get("files", {})
            for path_str, data in files_dict.items():
                self._entries[path_str] = FileImportData(
                    mtime_ns=data["mtime_ns"],
                    module=data["module"],
                    imports=tuple(data["imports"]),
                )
        except (OSError, json.JSONDecodeError, KeyError, ValueError):
            self._entries.clear()

    def save_cache(self) -> None:
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "version": CACHE_VERSION,
                "files": {
                    path: {
                        "mtime_ns": data.mtime_ns,
                        "module": data.module,
                        "imports": list(data.imports),
                    }
                    for path, data in self._entries.items()
                },
            }
            # Write atomically; a torn cache would be read as an empty graph.
            encoded = json.dumps(payload, indent=2)
            tmp_target = self.cache_path.with_suffix(".tmp")
            tmp_target.write_text(encoded, encoding="utf-8")
            tmp_target.replace(self.cache_path)
        except (OSError, TypeError, ValueError):
            pass

    def sync_files(self, paths: list[Path] | None = None) -> None:
        """Scan given files (or entire repository) updating stale entries in cache."""
        target_files = paths
        if target_files is None:
            target_files = []
            for d in ("edgar_sec", "tests"):
                dir_path = self.repo_root / d
                if dir_path.is_dir():
                    target_files.extend(dir_path.rglob("*.py"))

        active_rel_paths = set()
        for f in target_files:
            try:
                rel = str(f.relative_to(self.repo_root))
            except ValueError:
                continue
            active_rel_paths.add(rel)
            st = f.stat()
            existing = self._entries.get(rel)
            if existing and existing.mtime_ns == st.st_mtime_ns:
                continue
            mod_name, imports = parse_file_imports(f, rel)
            self._entries[rel] = FileImportData(
                mtime_ns=st.st_mtime_ns,
                module=mod_name,
                imports=imports,
            )

        if paths is None:
            stale = [p for p in self._entries if p not in active_rel_paths]
            for p in stale:
                del self._entries[p]

    def build_reverse_map(self) -> dict[str, set[str]]:
        """Map canonical module dotted names and file paths to dependent file paths."""
        reverse = defaultdict(set)
        for rel_path, data in self._entries.items():
            for imported in data.imports:
                reverse[imported].add(rel_path)
        return reverse

    def resolve_tests(
        self,
        changed_sources: tuple[str, ...],
        changed_tests: tuple[str, ...],
        changed_conftests: tuple[str, ...],
    ) -> TestSelectionResult:
        """Resolve all affected test files via direct mirrors, conftest scoping, and reverse AST traversal."""
        selected_tests: set[str] = set()
        reasons: dict[str, list[str]] = defaultdict(list)

        for t in changed_tests:
            if (self.repo_root / t).is_file():
                selected_tests.add(t)
                reasons[t].append("direct_test_edit")

        for s in changed_sources:
            if s == "check.py":
                checks_tests_dir = self.repo_root / "tests" / "foundation" / "checks"
                if checks_tests_dir.is_dir():
                    for t_file in checks_tests_dir.rglob("test_*.py"):
                        rel_t = str(t_file.relative_to(self.repo_root))
                        selected_tests.add(rel_t)
                        reasons[rel_t].append("check.py_unit_tests")
                continue
            mirror = find_mirror_test(s, self.repo_root)
            if mirror:
                selected_tests.add(mirror)
                reasons[mirror].append(f"mirror_of:{s}")

        for c in changed_conftests:
            c_dir = Path(c).parent
            for t_file in (self.repo_root / c_dir).rglob("test_*.py"):
                rel_t = str(t_file.relative_to(self.repo_root))
                selected_tests.add(rel_t)
                reasons[rel_t].append(f"scoped_conftest:{c}")

        reverse_map = self.build_reverse_map()
        queue: deque[str] = deque()
        visited: set[str] = set()

        for s in changed_sources:
            entry = self._entries.get(s)
            if entry:
                queue.append(entry.module)
                visited.add(entry.module)
            queue.append(s)
            visited.add(s)

        while queue:
            current = queue.popleft()
            dependents = reverse_map.get(current, set())
            for dep in dependents:
                if dep in visited:
                    continue
                visited.add(dep)

                if dep.startswith("tests/") and Path(dep).name.startswith("test_"):
                    selected_tests.add(dep)
                    reasons[dep].append(f"transitive_dependency_of:{current}")
                else:
                    queue.append(dep)
                    dep_entry = self._entries.get(dep)
                    if dep_entry:
                        queue.append(dep_entry.module)

        sorted_targets = tuple(sorted(selected_tests))
        return TestSelectionResult(
            test_files=sorted_targets,
            reasons=dict(reasons),
        )
