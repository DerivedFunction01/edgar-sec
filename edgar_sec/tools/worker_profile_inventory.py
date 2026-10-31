from __future__ import annotations

import hashlib
import importlib.metadata
import logging
import pathlib
import sys

logger = logging.getLogger(__name__)
logger.info("worker_profile_inventory module loaded")


def _normalized_selectors(selectors: list[str]) -> list[str]:
    normalized = []
    for item in selectors:
        path = pathlib.Path(item)
        if path.is_absolute():
            try:
                path = path.relative_to(pathlib.Path.cwd())
            except ValueError:
                pass
        normalized.append(path.as_posix())
    return sorted(normalized)


def scope_key(selectors: list[str]) -> str:
    normalized = _normalized_selectors(selectors)
    if normalized in (["tests"], ["tests/"]):
        return "suite:tests"
    if any("::" in item for item in normalized):
        payload = "\n".join(normalized)
        return f"ids:{hashlib.sha256(payload.encode()).hexdigest()}"
    if len(normalized) == 1:
        path = pathlib.Path(normalized[0])
        if path.is_dir():
            return f"folder:{path.as_posix().rstrip('/')}"
        if path.suffix == ".py":
            return f"file:{path.as_posix()}"
    payload = "\n".join(normalized)
    return f"mixed:{hashlib.sha256(payload.encode()).hexdigest()}"


def _selector_files(selectors: list[str]) -> list[pathlib.Path]:
    files: set[pathlib.Path] = set()
    for selector in selectors:
        path = pathlib.Path(selector.split("::", 1)[0])
        if path.is_absolute():
            try:
                path = path.relative_to(pathlib.Path.cwd())
            except ValueError:
                pass
        if path.is_file() and path.name.startswith("test_"):
            files.add(path)
        elif path.is_dir():
            files.update(path.rglob("test_*.py"))
    return sorted(files)


def _case_fingerprint(
    test_file: pathlib.Path, dependencies: tuple[str, ...] = ()
) -> str:
    from edgar_sec.foundation.hashing import file_sha256

    paths = [test_file, *(pathlib.Path(item) for item in dependencies)]
    parent = test_file.parent
    while parent != pathlib.Path(".") and parent != parent.parent:
        conftest = parent / "conftest.py"
        if conftest.is_file():
            paths.append(conftest)
        parent = parent.parent
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.as_posix().encode())
        digest.update(file_sha256(path).encode())
    return digest.hexdigest()


def execution_context_fingerprint() -> str:
    from edgar_sec.foundation.runtime.resources import (
        auto_worker_count,
        available_memory_bytes,
    )
    from edgar_sec.tools.fast_pytest_worker_calibrator import (
        detect_hardware_topology,
    )

    versions = {"python": sys.version, "pytest": importlib.metadata.version("pytest")}
    try:
        versions["xdist"] = importlib.metadata.version("pytest-xdist")
    except importlib.metadata.PackageNotFoundError:
        versions["xdist"] = "missing"
    config_hashes = {}
    for name in ("pytest.ini", "pyproject.toml", "tox.ini", "setup.cfg", "conftest.py"):
        path = pathlib.Path(name)
        if path.is_file():
            from edgar_sec.foundation.hashing import file_sha256

            config_hashes[name] = file_sha256(path)
    from edgar_sec.foundation.serialization import canonical_json

    hardware_topology = detect_hardware_topology()
    payload = {
        "versions": versions,
        "hardware_topology": hardware_topology,
        "worker_ceiling": auto_worker_count(
            available_memory_bytes(), cpu_cores=hardware_topology[1]
        ),
        "config": config_hashes,
    }
    return hashlib.sha256(canonical_json(payload).encode()).hexdigest()


def scope_inventory(
    selectors: list[str],
) -> tuple[list[pathlib.Path], str, dict[str, str], str]:
    files = _selector_files(selectors)
    from edgar_sec.foundation.checks.lineage import LineageGraph
    from edgar_sec.foundation.hashing import file_sha256
    from edgar_sec.foundation.serialization import canonical_json

    graph = LineageGraph(repo_root=pathlib.Path.cwd())
    graph.load_cache()
    graph.sync_files()
    graph.save_cache()
    dependencies = graph.dependency_files(tuple(path.as_posix() for path in files))
    fingerprints = {
        path.as_posix(): _case_fingerprint(path, dependencies.get(path.as_posix(), ()))
        for path in files
    }
    inventory = [
        {"path": path.as_posix(), "fingerprint": file_sha256(path)} for path in files
    ]
    context_fingerprint = execution_context_fingerprint()
    payload = {
        "environment": context_fingerprint,
        "inventory": inventory,
        "cases": fingerprints,
    }
    return (
        files,
        hashlib.sha256(canonical_json(payload).encode()).hexdigest(),
        fingerprints,
        context_fingerprint,
    )


def case_file(nodeid: str, files: list[pathlib.Path]) -> pathlib.Path:
    raw_path = nodeid.split("::", 1)[0]
    for path in files:
        if path.as_posix() == raw_path:
            return path
    return pathlib.Path(raw_path)


def folder_name(test_file: pathlib.Path) -> str:
    parts = test_file.parts
    try:
        index = parts.index("tests")
    except ValueError:
        return "_root"
    return parts[index + 1] if len(parts) > index + 2 else "_root"
